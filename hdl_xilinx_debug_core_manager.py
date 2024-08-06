#!/usr/bin/env python3

import re
import os
import json
import itertools

# TODO: For VIOs, add something to the comment format so that signals can have 
# a false path specified. In that case, the VIO would register that and would 
# generate false path constraints for these signals (and figure out in Vivado 
# how to reliably reference these signals...). But generally speaking, if you 
# have signals from different clock domains in one module that you all want to 
# have VIO controlled, it looks more handy to just use one VIO, and then either 
# sync the signal if it's important or just ignore the path. VIOs are slow af 
# compared to hardware, there is no point in worrying about metastability at 
# a VIO (in contrast to an ILA). Unless I overlook something of course, let's 
# see how well that statement ages.


class IlaSignal(object):
    """All the necessary fields for describing a signal that needs to be added 
    to an ILA
    """

    # TODO: actually adapt the re such that ila_name (or the signal name?) 
    # cannot have any '_'
    pattern_sig_sv = re.compile(
r'[\s]*(logic|reg|wire)[\s]+(\[([\d]+):([\d]+)\][\s]+){0,1}ila_ctrl_([a-zA-Z0-9]+)_([\w]+)[\s]*;([\s]*//[\s]*(trigger_type=([\w]+)[\s]*){0,1}[\s]*(comparators=([\d]+)){0,1}[\s]*){0,1}'
    )
    pattern_sig_clk_sv = re.compile(
r'[\s]*(logic|reg|wire)[\s]+ila_ctrl_([a-zA-Z0-9]+)_clk[\s]*;[\s]*'
    )

    def __init__(self, name="", width=1, ila_name="",
                 trigger_type="both", num_comparators=1, index=None):
        """
        trigger_type - can be 'data', 'trigger' or 'both'
        """
        self.name = name
        self.ila_name = ila_name
        self.width = width
        self.index = index
        self.num_comparators = num_comparators
        self.trigger_type = trigger_type

    @property
    def trigger_type_xilinx_id(self):
        """translate the human-readable object attribute into the xilinx 
        identifier digit for the respective trigger mode as the IP integrator 
        uses it
        """
        if self.trigger_type == 'both':
            return 0
        elif self.trigger_type == 'trigger':
            return 1
        else:
            # 'data' is the only possible option left
            return 2

    @classmethod
    def from_str(cls, s_input, hdl_lang="systemverilog"):
        """analyse a verilog/systemverilog line of code and look for a ila_ctrl 
        signal definition (not the ila clock). Returns the according ila signal object if it finds 
        an ila signal definition, otherwise 'None'.

        ILA signals need to be defined in the following way in 
        verilog/systemverilog files (for clock look below):
        "logic"/"reg"/"wire" [\[<width_upper>:<width_lower>\]] 
        ila_ctrl_<ila_name>_<name>; // trigger_type=<trigger_type> comparators=<num_comparators>
        - ila_name is the name of the specific ILA (there can be multiple ILAs 
          required even in one module, e.g. if you have multiple clock domains 
          to observe). ila_name can not contain any '_'!!! ila_name can not be empty.
        - no width is automatically interpreted as width = 1.
            - otherwise, width = width_upper - width_lower + 1
            the restriction here is, as is quite visible: No 
            placeholders/parameters/variables in the signal definition. The 
            widths need to be given explicitly (otherwise the line will be 
            ignored).
        - there can be an arbitrary amount of whitespaces in any spot that has 
          a whitespace in the format given (as long as it doesn't affect the 
          syntactical meaning of course)
        - trigger_type is the CONFIG.TYPE property of the ILA port. It specifies 
          if a signal is data, trigger, or both.

        The ila clock needs to have the name ila_<ila_name>_clk and be present 
        in the module. With that there is no need to match for the clock here, 
        it will always be named the same when generating the vio (so you don't 
        gain information from matching). Just require the user to implement the 
        signal, and if they fail to do so let the synthesis tool complain
        """

        if hdl_lang in ("systemverilog", "verilog"):

            # make sure you abort if you match the ila clock, because that is 
            # not supposed to be returned as a signal
            if cls.pattern_sig_clk_sv.match(s_input):
                return None

            mo = cls.pattern_sig_sv.match(s_input)
            if mo:
                # TODO: adapt the group indices in debugging
                # the match group indices are determined by just trying out
                if mo.group(3):
                    width_upper = int(mo.group(3))
                    width_lower = int(mo.group(4))
                    width = width_upper - width_lower + 1
                else:
                    width = 1
                ila_name = mo.group(5)
                name = mo.group(6)
                # (if radix and/or init are not given, mo.group({8,9}) exist, but 
                # are None. So no need for any existence check or try/except here)
                # TODO: don't forget that you still have to convert the trigger type 
                # to a number when writing the IP definition.
                trigger_type = mo.group(9)
                if mo.group(11):
                    num_comparators = mo.group(11)
                else:
                    num_comparators = 1
                return IlaSignal(name, width, ila_name, trigger_type, num_comparators)
            else:
                return None

        else:
            raise Exception(f"Language {hdl_lang} not supported (yet)")

    def print_instantiation(self, probe_index=0):
        """prints the line to be used within a verilog/systemverilog ila ctrl 
        module instantiation
        """
        # TODO: add a note to the instantiation that this is generated code

        return f"    .probe{self.index}             (ila_ctrl_{self.ila_name}_{self.name}),"


class VioSignal(object):
    """All the necessary fields for describing a signal that needs to be added 
    to a VIO

    VIO signals need to be defined in the following way in verilog/systemverilog 
    files (for clock look below):
    "logic"/"reg"/"wire" [\[<width_upper>:<width_lower>\]] 
    vio_ctrl_<"in"/"out">_<name>; // radix=<radix> init=<val>
    - no width is automatically interpreted as width = 1.
        - otherwise, width = width_upper - width_lower + 1
        the restriction here is, as is quite visible: No 
        placeholders/parameters/variables in the signal definition. The 
        widths need to be given explicitly (otherwise the line will be 
        ignored).
    - there can be an arbitrary amount of whitespaces in any spot that has 
      a whitespace in the format given (as long as it doesn't affect the 
      syntactical meaning of course)
    - <name> is the user name that the signal will eventually have in 
      vio_ctrl.tcl. It gets specified here
    - radix is the radix for the signal representation in the user vio 
      interface. If no radix is given, the vio will automatically determine 
      the radix for the signal (probably either binary or hex)
    - <val> is the initialization value for the signal that the vio core 
      will set at device initialization. Setting init is optional

    The vio clock needs to have the name vio_ctrl_clk and be present in the 
    module. With that there is no need to match for the clock here, it will 
    always be named the same when generating the vio (so you don't gain 
    information from matching). Just require the user to implement the signal, 
    and if they fail to do so let the synthesis tool complain
    """

    # the pattern of death... it does what is described above for the arbitrary 
    # signal names (not the clock)
    pattern_sig_sv = re.compile(
r'[\s]*(logic|reg|wire)[\s]+(\[([\d]+):([\d]+)\][\s]+){0,1}vio_ctrl_(in|out)_([\w]+)[\s]*;([\s]*//[\s]*(radix=([\w]+)[\s]*){0,1}[\s]*(init=([\w]+)){0,1}[\s]*){0,1}'
    )

    def __init__(self, name="", direction="input",
                 width=1, radix="binary", init=0, index=None):
        """
        radix - can be 'binary', 'hex' or 'decimal' (TODO: distinguish 
        signed/unsigned decimal, and maybe others if there are other radices 
        available for VIO ports)
        """
        # !!! THE ORDER OF THE FIELDS IS IMPORTANT HERE !!!
        # why you ask? Let's say there is an 'unexpected behavior' somewhere in 
        # the tcl json library: At least here when trying it with vivado 2019.1, 
        # if the last entry in a json object is an integer (without '"') , then 
        # for some reason the tcl library interprets that as a list, and not 
        # just as a string. Personal guess is that it has to do with parsing 
        # the comma, that normally closes the line and which is not there for 
        # the last line. The effect is: when importing the json vio ctrl signal 
        # description in vivado (generated by _write_json_sig_list), you end up 
        # with a list instead of an integer (or in tcl, a string) for that 
        # field which breaks every operation (like comparisons) that you would 
        # do on that field. (I have seen it with one integer as the last entry, 
        # one as a middle entry, the middle entry got parsed correctly...). The 
        # solution is: make sure that there is no integer entry in the last 
        # position. At least by the time of testing, the fields get written in 
        # the same order as the properties are registered with the VioSignal 
        # object. And that is the order in which they are given here, so by 
        # putting something like 'direction' at the end, which is guaranteed to 
        # be a string, you more or less circumvent the problem.
        self.name = name
        self.init = init
        self.index = index
        self.width = width
        self.radix = radix
        self.direction = direction

    @classmethod
    def from_str(cls, s_input, hdl_lang="systemverilog"):
        """analyse a verilog/systemverilog line of code and look for a vio_ctrl 
        signal definition (not the vio clock). Returns the according vio signal object if it finds 
        a vio signal definition, otherwise 'None'.
        """

        if hdl_lang in ("systemverilog", "verilog"):

            mo = cls.pattern_sig_sv.match(s_input)
            if mo:
                # the match group indices are determined by just trying out
                if mo.group(3):
                    width_upper = int(mo.group(3))
                    width_lower = int(mo.group(4))
                    width = width_upper - width_lower + 1
                else:
                    width = 1
                direction = mo.group(5)
                name = mo.group(6)
                # (if radix and/or init are not given, mo.group({8,9}) exist, but 
                # are None. So no need for any existence check or try/except here)
                # edit: still we need the check for mo.group(9) if we want to apply 
                # (upper()), because otherwise you are calling something on a None 
                # object...
                if mo.group(9):
                    radix = mo.group(9).upper()
                else:
                    radix = ""
                init = mo.group(11)
                return cls(name, direction, width, radix, init)
            else:
                return None

        else:
            raise Exception(f"Language {hdl_lang} not supported (yet)")

    def print_instantiation(self, probe_index=0):
        """prints the line to be used within a verilog/systemverilog vio ctrl 
        module instantiation (".probe...<probe_index>     (<signal>))

        probe_index: probe index for the given group ('in' or 'out').
        """
        # purely inserting a space for cosmetics, to make sure that in the
        # instantiation the ports are aligned no matter if the direction
        # string would have 2 or 3 letters...
        s_direction_index = f"in{probe_index} " if self.direction == "in" \
                            else f"out{probe_index}"
        # the line is only too long so that the indentation looks good in the 
        # eventual file...
        return f"    .probe_{s_direction_index}             (vio_ctrl_{self.direction}_{self.name}),"


class XilinxDebugCore(object):
    """generic attributes for xilinx debug cores. Meant as an abstract 
    superclass to XilinxIlaCore and XilinxVioCore
    """

    def __init__(self):
        super.__init__()


class XilinxIlaCore(XilinxDebugCore):

    def __init__(self, signals, module_name, name):
        self.signals = signals
        self.module_name = module_name
        self.name = name

    def generate_ip_instantiation(self, hdl_lang):
        """
        always generates lines of code for the instantiation of ONE core.
        Returns: A list of strings, representing the lines of verilog code for the 
        ila core instantiation
        """

        l_lines = [
f"xip_ila_ctrl_{self.module_name}_{self.name} inst_xip_ila_ctrl"
f"_{self.module_name}_{self.name} (",
f"    .clk                    (ila_ctrl_{self.name}_clk),"]

        # theoretically you wouldn't have to separate in and out signals here, but 
        # it looks nice in the rtl file
        for index, signal in enumerate(self.signals):
            l_lines.append(signal.print_instantiation(index))

        # remove the ',' from the last line of signal connection
        s_last_line = l_lines.pop()
        l_lines.append(s_last_line.replace(',',''))

        l_lines.append(");")

        return l_lines

    @classmethod
    def from_module(cls, s_module_file_name):
        """analyse an hdl module for vio-connected signal definitions
        """
        module_name, hdl_lang = XilinxDebugCoreManager.parse_module_file_name(s_module_file_name)

        with open(s_module_file_name, 'r') as f_in:
            l_lines = f_in.readlines()

        # it is possible to have multiple ILAs defined in one module. Therefore,
        # we have to make a list of cores here
        l_ila_cores = []
        l_detected_ila_names = []
        # counter to hold the indices with which the signals will be 
        # connected to the ila ports.
        count_ports = []
        for line in l_lines:
            ila_ctrl_sig = IlaSignal.from_str(line, hdl_lang)
            if ila_ctrl_sig:

                try:
                    # TODO: figure out which Exception to listen to
                    core_index = l_detected_ila_names.index(ila_ctrl_sig.ila_name)
                except Exception:
                    core_index = -1

                if core_index >= 0:
                    core = l_ila_cores[core_index]
                    count_ports[core_index] = count_ports[core_index] + 1
                    ila_ctrl_sig.index = count_ports[core_index]
                    core.signals.append(ila_ctrl_sig)
                else:
                    core = cls([ila_ctrl_sig], module_name, ila_ctrl_sig.ila_name)
                    l_ila_cores.append(core)
                    count_ports.append(0)
                    l_detected_ila_names.append(ila_ctrl_sig.ila_name)
                    ila_ctrl_sig.index = 0

        if l_ila_cores:
            return l_ila_cores
        else:
            return None

    def generate_ip_declaration(self):
        """generate the tcl code lines for declaring the ILA IP in the format 
        that the code manager can process, in order to add the IP to the Vivado 
        project
        """

        l_lines = []
        l_lines.extend([
    "lappend xips [dict create                                   \\",
    f"    name                    xip_ila_ctrl_{self.module_name}_{self.name} \\",
    "    ip_name                 ila                           \\",
    "    ip_vendor               xilinx.com                    \\",
    "    ip_library              ip                            \\",
    "    config [dict create                                     \\"
        ])

        for signal in self.signals:
            # TODO: add num comparators here, as soon as you know how exactly 
            # that config field is named
            l_lines.extend([
    f"        CONFIG.C_PROBE{signal.index}_WIDTH {{{signal.width}}} \\",
    f"        CONFIG.C_PROBE{signal.index}_TYPE {{{signal.trigger_type_xilinx_id}}} \\",
            ])

        # write other config
        # TODO: parameterizable solution for the DATA DEPTH (now hardcoded)
        l_lines.extend([
    f"        CONFIG.C_NUM_OF_PROBES                  {{{len(self.signals)}}} \\",
    "        CONFIG.C_DATA_DEPTH                     {{16384}}                  \\",
    "        ]                                                                   \\",
    "    ]"
        ])

        return l_lines


class XilinxVioCore(XilinxDebugCore):

    def __init__(self, signals, module_name):
        self.signals = signals
        self.module_name = module_name

    def write_json_sig_list(self, file_name):
        """write a list of vio control signals into a json file, such that it can 
        later easily be picked up vio_ctrl.tcl
        """

        # transform the list of VioSignal objects into a list of dictionaries
        l_vio_ctrl_signals_dicts = [x.__dict__ for x in self.signals]

        # load the existing definitions, update the one for this module and 
        # write back the definitions
        vio_ctrl_signals = {}
        if os.path.isfile(file_name):
            with open(file_name, 'r') as f_in:
                vio_ctrl_signals = json.load(f_in)

        vio_ctrl_signals[self.module_name] = l_vio_ctrl_signals_dicts

        with open(file_name, 'w') as f_out:
            json.dump(vio_ctrl_signals, f_out, indent=4)

    def generate_ip_instantiation(self, hdl_lang):
        """
        always generates lines of code for the instantiation of ONE core.
        Returns: A list of strings, representing the lines of verilog code for the 
        vio control core instantiation
        """

        # I know, list plus filter is not necessarily what you should, but these 
        # lists are probably not gonna contain >1e4 entries...
        l_signals_in = list(filter(lambda x: x.direction == 'in', self.signals))
        l_signals_out = list(filter(lambda x: x.direction == 'out', self.signals))

        if hdl_lang in ("systemverilog", "verilog"):
            l_lines = [
        f"xip_vio_ctrl_{self.module_name} inst_xip_vio_ctrl_{self.module_name} (",
        "    .clk                    (vio_ctrl_clk),"]

            # theoretically you wouldn't have to separate in and out signals here, but 
            # it looks nice in the rtl file
            for index, signal in enumerate(l_signals_in):
                l_lines.append(signal.print_instantiation(index))
            for index, signal in enumerate(l_signals_out):
                l_lines.append(signal.print_instantiation(index))

            # remove the ',' from the last line of signal connection
            s_last_line = l_lines.pop()
            l_lines.append(s_last_line.replace(',',''))

            l_lines.append(");")

            return l_lines
        else:
            raise Exception(f"Invalid language: {hdl_lang}")

    @classmethod
    def from_module(cls, s_module_file_name):
        """analyse an hdl module for vio-connected signal definitions
        """
        module_name, hdl_lang = XilinxDebugCoreManager.parse_module_file_name(s_module_file_name)

        with open(s_module_file_name, 'r') as f_in:
            l_lines = f_in.readlines()

        l_signals = []
        # counters to hold the indices with which the signals will be connected to 
        # the vio ports -> that's also what the vio_ctrl.tcl will eventually 
        # utilize in order to map vio ports to user signal names and vio-internal 
        # port names.
        counts_vio_ports = {'in': 0, 'out': 0}
        for line in l_lines:
            signal = VioSignal.from_str(line, hdl_lang=hdl_lang)
            if signal:
                signal.index = counts_vio_ports[signal.direction]
                # for the 10000th time, where on earth is the += in python?
                counts_vio_ports[signal.direction] = counts_vio_ports[signal.direction] + 1
                l_signals.append(signal)

        if l_signals:
            return cls(l_signals, module_name)
        else:
            return None

    def generate_ip_declaration(self):
        """generate the tcl code lines for declaring the VIO IP in the format 
        that the code manager can process, in order to add the IP to the Vivado 
        project
        """

        l_lines = []
        l_lines.extend([
    "# xilinx ip for top level hardware control vio",
    "lappend xips [dict create                                   \\",
    f"    name                    xip_vio_ctrl_{self.module_name} \\",
    "    ip_name                 vio                           \\",
    "    ip_vendor               xilinx.com                    \\",
    "    ip_library              ip                            \\",
    "    config [dict create                                     \\"
        ])
        # needed to pass the total number of probes to the vio ip config
        count_num_probe = {"in": 0, "out": 0}

        for signal in self.signals:
            count_num_probe[signal.direction] = count_num_probe[signal.direction] + 1
            l_lines.append(
    f"        CONFIG.C_PROBE_{signal.direction.upper()}{signal.index}_WIDTH {{{signal.width}}} \\")
            if signal.init:
                l_lines.append(
    f"        CONFIG.C_PROBE_{signal.direction.upper()}{signal.index}_INIT_VAL {{0x{signal.init}}} \\")

        # write number of probes
        l_lines.extend([
    f"        CONFIG.C_NUM_PROBE_IN                   {{{count_num_probe['in']}}}         \\",
    f"        CONFIG.C_NUM_PROBE_OUT                  {{{count_num_probe['out']}}}         \\",
    "        CONFIG.C_EN_PROBE_IN_ACTIVITY           {1}                         \\",
    "        ]                                                                   \\",
    "    ]"
        ])

        return l_lines


class XilinxDebugCoreManager(object):
    """provide functionality to generate all the necessary code for a vio_ctrl 
    core (instantiating, xilinx IP declaration and signal configuration for 
    interpretation by vio_ctrl.tcl).  Therefore, this class is more of 
    a semantical collection of methods than that it provides actual object-style 
    functionality. It only exists for a better code structure (and maybe for 
    protecting some sub-methods which have no point in being accessible from 
    outside of this class's API).
    The API of this class is basically solely process_verilog_module()
    """

    S_GENERATED_CODE_START = "    /* --- GENERATED CODE --- */"
    S_GENERATED_CODE_END = "    /* ---------------------- */"

    def __init__(self, vio_cores={}, ila_cores={}):
        # vio_cores and ila_cores are dict(XilinxDebugCore). The key is the name 
        # of the module in which the respective core is defined
        self._vio_cores = vio_cores
        self._ila_cores = ila_cores

    # defining vio_cores and ila_cores as properties for convenience: You 
    # sometimes need the dict with the module names, and sometimes just the list 
    # of the cores without the module information. This way, you have easy 
    # access to both of those.
    @property
    def dict_vio_cores(self):
        return self._vio_cores

    @property
    def list_vio_cores(self):
        return list(self._vio_cores.values())

    @property
    def dict_ila_cores(self):
        return self._ila_cores

    @property
    def list_ila_cores(self):
        return list(itertools.chain(*(self._ila_cores.values())))

    @staticmethod
    def parse_module_file_name(s_module_file_name):
        """from a module file name, extract the module name (the basename) and 
        the language (identified by the file extension)
        returns: (module_name, hdl_language)
        """
        l_fields = os.path.basename(s_module_file_name).split('.')
        module_name = l_fields[0]
        if l_fields[1] == "sv":
            hdl_lang = "systemverilog"
        elif l_fields[1] == "v":
            hdl_lang = "verilog"
        elif l_fields[1] == "vhd":
            hdl_lang = "vhdl"
        else:
            raise Exception(f"Invalid file extension: {l_fields[1]}")

        return module_name, hdl_lang

    @staticmethod
    def get_signal_formats(print_output=False):
        """return the required formats for vio_ctrl and ila signals as lines to 
        be printed (without newline characters)
        If print_output==True, also print the signal formats right-away.
        """
        l_output_lines = [
"Required signal naming convention for signals that invoke a xilinx debug core",
"There can be multiple ILAs in one module, but only one VIO",
"Passing the commented specifiers (trigger_type etc) is optional",
"TODO: radices for the VIO cores are not being processed yet",
"ila_ctrl_<ila_name>_<name>; // trigger_type=<trigger_type> comparators=<num_comparators>",
"vio_ctrl_<'in'/'out'>_<name>; // radix=<radix> init=<val>",
"The debug core names will be as follows:",
"ILA: xip_ila_ctrl_<module_name>_<ila_name>",
"VIO: xip_vio_ctrl_<ila_name>",
                ]
        if print_output:
            for line in l_output_lines:
                print(line)

        return l_output_lines

    def write_xips_declaration(self, s_xip_declaration_file_name):
        """write the xip declaration in the format such that the code 
        manager-generated scripts can add the IPs to the Vivado project
        """

        l_lines_out = []

        first_core = True
        for core in itertools.chain(self.list_vio_cores, self.list_ila_cores):
            if first_core:
                l_lines_out.extend([
                    "# --- GENERATED CODE --- */",
                    "set xips []",
                    "",
                ])
                first_core = False
            l_lines_out.extend(core.generate_ip_declaration())
            l_lines_out.append("")

        if not first_core:
            l_lines_out.extend([
            "# ---------------------- */",
            ])

        with open(s_xip_declaration_file_name, 'w') as f_out:
            f_out.writelines([x+'\n' for x in l_lines_out])

    def _parse_module(self, s_module_file_name):
        """Searches a given HDL module file for ila and vio definitions, and 
        adds them to self._vio_cores/_ila_cores, or updates those. The method 
        does not write to any files, thus also it is not updating any 
        instantiations in s_module_file_name.
        """
        module_name, hdl_lang = XilinxDebugCoreManager.parse_module_file_name(s_module_file_name)
        self._vio_cores[module_name] = XilinxVioCore.from_module(s_module_file_name)
        self._ila_cores[module_name] = XilinxIlaCore.from_module(s_module_file_name)

    def _update_module(self, s_module_file_name):
        """in a given HDL file, update all present instantiations of debug cores 
        with list_ila_cores and list_vio_cores
        The method does not analyse the module file for cores that are defined 
        (by defining the according signals). The function only exists for 
        logically splitting module analysis from instantiation update.
        """

        module_name, hdl_lang = self.parse_module_file_name(s_module_file_name)

        # pattern to match the first line of an instantiation of any debug core 
        # in module_name
        # (TODO: is there any point in being more specific here, in the sense 
        # that you only match against known cores? It should be enough to just 
        # match anything that meets the general structure of a debug core 
        # instantiation, and assume that there is no such structure in the code 
        # that has not been generated by this module
        s_pattern_inst_vio = r'[\s]*xip_vio_ctrl_' + module_name + r'[\s]+inst_xip_vio_ctrl_'   \
            + module_name + r'[\s]*\([\s]*'
        s_pattern_inst_ila = r'[\s]*xip_ila_ctrl_' + module_name + r'_[a-zA-Z0-9]+'             \
            + r'[\s]+inst_xip_ila_ctrl_' + module_name + r'_[a-zA-Z0-9]+[\s]*\([\s]*'
        s_pattern_inst_debug_core = r'(' + s_pattern_inst_vio + '|' + s_pattern_inst_ila + r')'
        pattern_inst_debug_core = re.compile(s_pattern_inst_debug_core)

        with open(s_module_file_name, 'r') as f_in:
            l_lines_old = f_in.readlines()

        # TODO: when processing the lines of the old file, also remove any 
        # notifictians that code is generated -> globally define those, so that 
        # it's easy to reference

        # just create a new list of lines based on the old list of lines. Nobody 
        # said that this would be great, elegant, or efficient. Just needs to 
        # work...
        l_lines_new = []
        # theoretically, pointer_in_module_inst might be obsolete because 
        # everything that would trigger it should be enclosed in 
        # pointer_in_generated_code blocks. But it was here before 
        # pointer_in_generated_code. And also, "theoretically"... If ever 
        # someone or something removes the generated code notifiers, it's nice 
        # if that doesn't fully break this function.
        pointer_in_module_inst = False
        pointer_in_generated_code = False
        for line in l_lines_old:
            if not pointer_in_module_inst:
                # first match for an existing debug core instantiation, then for 
                # the end of the module definition

                if pattern_inst_debug_core.match(line):
                    pointer_in_module_inst = True
                elif line.find(self.S_GENERATED_CODE_START) != -1:
                    pointer_in_generated_code = True
                elif line.find(self.S_GENERATED_CODE_END) != -1:
                    pointer_in_generated_code = False

                elif re.match(r'[\s]*endmodule[\s]', line):
                    # we have to add the line breaks to the list that we get 
                    # from the function (yes, you could've also made that 
                    # a parameter to the function...)
                    l_lines_new.append(self.S_GENERATED_CODE_START + "\n")
                    for core in self.dict_ila_cores[module_name]:
                        l_lines_new.extend(
                            [x+"\n" for x in core.generate_ip_instantiation(hdl_lang)])
                        l_lines_new.append("\n")
                    if self.dict_vio_cores[module_name]:
                        core = self.dict_vio_cores[module_name]
                        l_lines_new.extend(
                            [x+"\n" for x in core.generate_ip_instantiation(hdl_lang)])
                        l_lines_new.append("\n")
                    # remove the empty line after the last module instantiation
                    l_lines_new.pop()
                    l_lines_new.append(self.S_GENERATED_CODE_END + "\n")
                    # add the endmodule line after instantiating the debug cores
                    l_lines_new.append(line)
                    break
                else:
                    # checking for pointer_in_generated_code, because that 
                    # prevents adding empty lines between the debug that will 
                    # get generated (meaning you would otherwise add an empty 
                    # line with every call)
                    if not pointer_in_generated_code:
                        l_lines_new.append(line)
            else:
                # match end of module instantiation
                if re.match(r'[\s]*\)[\s]*;[\s]*', line):
                    pointer_in_module_inst = False

        with open(s_module_file_name, 'w') as f_out:
            f_out.writelines(l_lines_new)

    def process_module(self, s_module_file_name,
                       s_json_file_name_signals="vio_ctrl_signals.json",
                       s_xip_declaration_dir="xips/xips_debug_cores.tcl"):
        """update the debug core instantiation in a verilog module:
        - find vio_ctrl signal definitions (see parse_verilog_module)
        - write/update the vio_ctrl signals json file (to be read by 
          vio_ctrl.tcl when loading)
        - edit the verilog module file to hold an up-to-date instantiation of the 
          vio_ctrl ip: Scan the module for an existing instantiation, if you find 
          one, remove that. Insert the new instantiation at the very end of the 
          module (that is, right before 'endmodule')
        """

        module_name, hdl_lang = self.parse_module_file_name(s_module_file_name)
        self._parse_module(s_module_file_name)

        self._update_module(s_module_file_name)
        self.dict_vio_cores[module_name].write_json_sig_list(s_json_file_name_signals)

        s_xip_declaration_file_name = os.path.join(
                s_xip_declaration_dir, "xips_debug_cores_" + module_name + ".tcl")
        self.write_xips_declaration(s_xip_declaration_file_name)


#         ##############################
#         # RTL MODULE FILE
#         ##############################
# 
#         with open(s_module_file_name, 'r') as f_in:
#             l_lines_old = f_in.readlines()
# 
#         # just create a new list of lines based on the old list of lines. Nobody 
#         # said that this would be great, elegant, or efficient. Just needs to 
#         # work...
#         l_lines_new = []
#         pointer_in_module_inst_vio_ctrl = False
#         for l in l_lines_old:
#             if not pointer_in_module_inst_vio_ctrl:
#                 # match for an existing vio_ctrl instantiation, then for the end of 
#                 # the module definition
#                 if re.match(r'[\s]*xip_vio_ctrl[\s]+inst_xip_vio_ctrl[\s]*\([\s]*', l):
#                     pointer_in_module_inst_vio_ctrl = True
#                 elif re.match(r'[\s]*endmodule[\s]', l):
#                     # we have to add the line breaks to the list that we get 
#                     # from the function (yes, you could've also made that 
#                     # a parameter to the function...)
#                     l_lines_new.extend(
#                         [l+"\n" for l in self._generate_ip_instantiation(l_vio_ctrl_signals)])
#                     l_lines_new.extend(["\n", l])
#                     break
#                 else:
#                     l_lines_new.append(l)
#             else:
#                 if re.match(r'[\s]*\)[\s]*;[\s]*', l):
#                     pointer_in_module_inst_vio_ctrl = False
# 
#         with open(s_module_file_name, 'w') as f_out:
#             f_out.writelines(l_lines_new)
# 
#         ##############################
#         # JSON VIO SIGNALS
#         ##############################
# 
# 
#         ##############################
#         # VIO XILINX IP DEFINITION FILE
#         ##############################
# 
#         self._write_vio_ip_declaration(l_vio_ctrl_signals, s_xip_vio_ctrl_file_name)


# if __name__ == "__main__":
#     s_file_in = "rtl/top.sv"
# #     l_vio_ctrl_signals = parse_verilog_module(s_file_in) 
# #     l_vio_inst_lines = _generate_ip_instantiation(l_vio_ctrl_signals)
# #     for l in l_vio_inst_lines:
# #         print(l)
# #     write_json_sig_list(l_vio_ctrl_signals, "vio_ctrl_signals.json")
#     process_verilog_module(s_file_in)
