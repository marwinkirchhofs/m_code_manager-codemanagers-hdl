#!/usr/bin/env python3

# PYTHON PROJECT_CREATE
#
# Create a python project from the template in this directory

import os
import re
import shutil
import json
from operator import itemgetter
import inspect

import code_manager
from .hdl_module_interface import HdlModuleInterface
from .hdl_xilinx_debug_core_manager import XilinxDebugCoreManager
from m_code_manager.util.mcm_config import McmConfig


LANG_IDENTIFIERS = ["hdl"]
HDL_PROJECT_TYPES = ["xilinx", "lattice"]


class _BoardSpecs():
    # TODO: derive part from board_part

    # TODO: maybe that /usr/local/share part should be a project-wide variable 
    # somewhere
    PATH_CONSTRAINT_FILES_DEFAULT = "/usr/local/share/m_code_manager/hdl/constraints"

    def __init__(self, xilinx_board_specifier, constraints_file):
        """
        :constraints_file: path(!) to the constraints file - for specifying 
        a constraints file in a standard location via name, or deriving it from 
        the xilinx_board_specifier, use the factory method get_board_specs_obj
        """
        self.xilinx_board_specifier = xilinx_board_specifier
        self.constraints_file = constraints_file

    @property
    def constraints_file_name(self):
        return os.path.basename(self.constraints_file)

    @classmethod
    def get_board_specs_obj(cls, xilinx_board_specifier, constraints_file_name="",
                            global_config: McmConfig = None):
        """If no constraints_file_name is given, the function tries to obtain the 
        correct one from a set of predefined constraint file name formats (such 
        as digilent). The idea: For every board, you need the xilinx board 
        specifier (for setting the part in the project) and the master 
        constraints file name (for copying that one into the project if it is 
        available). One could now
        - let the user pass both the board specs and the constraints file as 
          options, but basically that's passing the same information twice
        - set up all supported boards manually as tupels here; tedious and 
          potentially unneccessary, because:
        For digilent boards for instance, the master constraints file from their 
        website seem to follow a fixed naming convention (as of 2024-03-26...).  
        So basically if you just bulk-download them, you should be able to 
        derive the correct constraints file from the board specifier. (note that 
        the constraints files are not included in the xilinx board parts. The 
        XMLs have something that looks similar, but that is actually the pin 
        connections for standard IPs like an I2C core)

        conclusion: whenever adding support for boards from a new vendor, check 
        if they have a naming convention, and if so add that to 
        __find_constraints_file.

        :constraints_file_name: Takes precedence over xilinx_board_specifier for 
        obtaining the constraints file. Can be either a file name, or a path 
        (absolute, or relative from project top level). Function fails if 
        constraints_file_name is given and does not resolve into an existing 
        file (instead of falling back to file name based on 
        xilinx_board_specifier)

        :raises: FileNotFoundError (see constraints_file_name, but also if file 
        finding via xilinx_board_specifier fails)
        """
        constraints_file = cls.__find_constraints_file(
                xilinx_board_specifier, constraints_file_name, global_config)

        if not constraints_file:
            if constraints_file_name:
                raise FileNotFoundError(
f"""No matching constraints file could be found for constraints file name 
'{constraints_file_name}' (board specifier '{xilinx_board_specifier}')""")
            else:
                raise FileNotFoundError(
f"""No matching constraints file could be found for board specifier 
'{xilinx_board_specifier}'""")
        else:
            return cls(xilinx_board_specifier, constraints_file)

    @classmethod
    def __find_constraints_file(cls, xilinx_board_specifier, constraints_file_name="",
                                global_config: McmConfig = None):
        """find the constraints file for a given board specifier, by checking if 
        consraints_file_name itself is an existing path, and reverting to known 
        constraints file formats and the respective directories otherwise
        """

        if os.path.isfile(constraints_file_name):
            return constraints_file_name

        path_constraint_files = ""
        if global_config:
            path_constraint_files = global_config.get("constraints")
        if not path_constraint_files:
            path_constraint_files = cls.PATH_CONSTRAINT_FILES_DEFAULT

        if os.path.isfile(os.path.join(path_constraint_files, constraints_file_name)):
            return os.path.join(path_constraint_files, constraints_file_name)

        l_constraint_files = os.listdir(path_constraint_files)

        # DIGILENT
        # digilent naming convention: arty-a7-35 -> Arty-A7-35-Master.xdc
        # the simple solution: append "-master.xdc" and do a case-insensitive 
        # match
        xdc_file_name_lower_case = xilinx_board_specifier + "-master.xdc"
        pattern = re.compile(xdc_file_name_lower_case, re.IGNORECASE)
        # (might not be the prime usage of an iterator to straight-up compress 
        # it into a list, but it does the trick here)
        l_matches = list(filter(pattern.match, l_constraint_files))
        if l_matches:
            # classic, take the first list element, because if the list has more 
            # than one element, you have already messed up anyways
            return os.path.join(path_constraint_files, l_matches[0])

        # TODO: as a fallback, provide an option to custom implement tupels with 
        # prepared constraints files

        # not found?
        return None


class HdlCodeManager(code_manager.CodeManager):

    # changed placeholders:
    # DIR_TCL -> DIR_SCRIPTS
    # DIR_XIPS -> DIR_XILINX_IPS
    # TCL_FILE_* -> SCRIPT_*
    PLACEHOLDERS = {
            'DIR_RTL':                      "rtl",
            'DIR_SIM':                      "sim",
            'DIR_SCRIPTS':                  "scripts",
            'DIR_SCRIPTS_XIL':              "scripts_xil",
            'DIR_XILINX_IPS':               "xips",
            'DIR_XIP_CTRL':                 "xip_ctrl",
            'DIR_CONSTRAINTS':              "constraints",
            'DIR_TB':                       "tb",
            'DIR_HW_EXPORT':                "build",
            'DIR_XILINX_HW_BUILD_LOG':      "hw_build_log",
            'DIR_BLOCKDESIGN':              "bd",
            'SCRIPT_READ_SOURCES':          "read_sources.tcl",
            'SCRIPT_BUILD_HW':              "build_hw.tcl",
            'SCRIPT_XILINX_IP_GENERATION':  "generate_xips.tcl",
            'SCRIPT_MANAGE_XIL_PRJ':        "manage_project.tcl",
            'SCRIPT_CREATE_PROJECT':        "create_project.tcl",
            'SCRIPT_SOURCE_HELPERS':        "source_helper_scripts.tcl",
            'SCRIPT_READ_JSON_VAR':         "get_json_variable.py",
            'SCRIPT_MANAGE_BUILDS':         "manage_build_files.bash",
            'SCRIPT_XILINX_VIO_CONTROL':    "vio_ctrl.tcl",
            'FILE_PROJECT_CONFIG':          "project_config.json",
            'FILE_MAKE_VARIABLES':          "var.make",
            'FILE_XILINX_VIO_CONTROL_SIGNALS_CONFIG':   "vio_ctrl_signals.json",
            'FILE_XILINX_IP_DEF_USER':      "xips_user.tcl",
            'FILE_XILINX_IP_DEBUG_CORES':   "xips_debug_cores.tcl",
            'FILE_TB_SV_IFC_RST':           "ifc_rst.sv",
            'FILE_TB_SV_UTIL_PKG':          "util_pkg.sv",
            'COMMAND_PROG_FPGA':            "program_fpga",
            'COMMAND_BUILD_HW':             "build_hw",
            'COMMAND_UPDATE':               "update",
    }

    PROJECT_SUBMODULES = {
            "xilinx": {
                "scripts_xilinx": {
                    "path": "scripts_xil",
                }
            },
            "lattice": {
            },
    }

    def __init__(self):
        # why passing the language to the base class init? See (way too 
        # extensive) comment in python_code_manager
        self.xilinx_debug_core_manager = XilinxDebugCoreManager()
        self.project_config = self._load_project_config()

        self.static_submodules = {
                "scripts": {
                    "path": ""
                },
                "sim_util_pkg": {
                    "path": "tb/util"
                },
                "sim_axi_pkg": {
                    "path": "tb/axi"
                },
        }

        super().__init__("hdl")

    COMMAND_DESC_PROJECT = \
    """Creates (and also updates) an HDL project for the respective vendor 
toolchain. For more information please refer to the help messages of the vendor 
subcommands.
"""

    SUBCOMMAND_DESC_PROJECT_XILINX = \
    """Nice, you chose to work with a Xilinx device, apparently. May god help you...
"""

    SUBCOMMAND_DESC_PROJECT_LATTICE = \
    """So, you chose to work with lattice instead of something like Xilinx? Well, 
that sounds like a very reasonable choice, so congrats to you! Unfortunately, 
this project doesn't actually support lattice yet in any way, the subcommand 
more or less just here for testing purposes, and to remind myself to definitely 
get into that at some point. Sorry about that...
"""

    def _get_submodules(self):
        """read the project_type of the current project, if 
        a FILE_PROJECT_CONFIG exists in the current working directory (aka if 
        you are in a project directory). Depending on the project type, add the 
        submodules belonging to that vendor to the static self.static_submodules
        """
        if os.path.exists(self.PLACEHOLDERS['FILE_PROJECT_CONFIG']):
            with open(self.PLACEHOLDERS['FILE_PROJECT_CONFIG'], 'r') as f_in:
                project_config = json.load(f_in)
            try:
                project_type = project_config["project_type"]
            except KeyError:
                project_type = ""

            if project_type:
                dynamic_submodules = self._get_dynamic_submodules(project_type)

            return {**self.static_submodules, **dynamic_submodules}
        else:
            return self.static_submodules

    def _get_dynamic_submodules(self, project_type):
        if project_type in HDL_PROJECT_TYPES:
            return self.PROJECT_SUBMODULES[project_type]
        else:
            return {}

    # TODO: with the enforced git repo for projects, _command_project can't act 
    # anymore from within an existing project: remove everything that does not 
    # assume that you are within an existing project; make sure that for 
    # everything that you would want to change on an existing project, there is 
    # a specific command
    def _command_project(self, subcommand=HDL_PROJECT_TYPES,
                         target=None, part=None, board_part=None, top=None,
                         hdl_lib=None, xil_tool=None,
                         **kwargs):
        """Creates the skeleton for an hdl project as generic as possible. That 
        mainly is, create the hdl project directory structure and add common 
        build scripts like makefile and vivado project generation script (given 
        that a xilinx project is asked for)

        !!! The method can create a new project, including project directory, or 
        act from within an existing project directory. This is decided on 
        whether or not target is not specified (which means passing a -t 
        option to m_code_manager or not). !!!

        An existing project will never be deleted. If the user confirms to 
        edit/overwrite an existing directory, that means that the contents will 
        be added to the existing directory (instead of doing nothing). The 
        design guideline is to really only delete files when that is 
        unambiguously confirmed. In this case, if the user really wants an 
        entirely new project, they can easily delete an existing one manually.
        """

        # TODO: temporary rtl directory structure. So far, everything gets 
        # dumped into 'rtl' with no subdirectories whatsoever. Works for small 
        # projects, not ideal for larger projects, but that's something to 
        # address later on.

        ##############################
        # PROJECT DIRECTORY
        ##############################
        if target is not None:
            prj_name = target
            if self._check_target_edit_allowed(prj_name):
                try:
                    os.mkdir(prj_name)
                except FileExistsError:
                    # no need to handle the exception if the directory prj_name 
                    # exists, that's taken care of and confirmed in 
                    # self._check_target_edit_allowed
                    pass
                os.chdir(prj_name)

        ##############################
        # SUBDIRECTORIES
        ##############################
        # some directories are omitted here: xips, bd
        # reason: they really only makes sense when the respective feature is 
        # used, and it's less likely/unintended that the user is going to edit 
        # or create things in these directories without going through the 
        # codemanager flow. Let's see how many days it takes until I get proven 
        # wrong about the last sentence (today is the 2024-03-24)...
        project_dirs = itemgetter(
                'DIR_RTL', 'DIR_CONSTRAINTS', 'DIR_SIM', 'DIR_TB',
                'DIR_XILINX_HW_BUILD_LOG', 'DIR_HW_EXPORT',
                'DIR_XILINX_IPS',
                )(self.PLACEHOLDERS)
        for directory in project_dirs:
            # it's not necessary to run a 'file allowed to be edited' check here, 
            # since os.mkdir never deletes anything. It only throws an exception 
            # if the directory exists.
            try:
                os.mkdir(directory)
            except FileExistsError:
                # again, if a project directory already exists, that's fine 
                # (assuming that it's a directory, theoretically could be 
                # a file as well. but at some point users gotta act 
                # reasonably, such as not to create files with meaningful 
                # names and without file extensions)
                pass

        ############################################################
        # SCRIPTING
        ############################################################

        ##############################
        # TCL SCRIPTS
        ##############################

        # XILINX PROJECT
        if subcommand == "xilinx":
            # default values for non-passed arguments
            if part is not None:
                part = part
            else:
                part = ""
            if board_part is not None:
                board_specs = _BoardSpecs.get_board_specs_obj(
                        board_part, global_config=self.global_config)
            else:
                board_specs = _BoardSpecs("", "")

            # xilinx IP definition file
            s_target_file = os.path.join(
                    self.PLACEHOLDERS['DIR_XILINX_IPS'],
                    self.PLACEHOLDERS['FILE_XILINX_IP_DEF_USER'])
            if self._check_target_edit_allowed(s_target_file):
                template_out = self._load_template("xips_def_user")
                self._write_template(template_out, s_target_file)

            ##############################
            # CONSTRAINTS FILE
            ##############################
            # TODO: implement something that processes a master constraints file, 
            # in the sense that it splits it up in timing and physical 
            # constraints - and make that a selectable option, because some 
            # people don't like splitting up makefiles
            if board_specs.constraints_file:
                s_target_file = os.path.join(
                        self.PLACEHOLDERS['DIR_CONSTRAINTS'], board_specs.constraints_file_name)
                if self._check_target_edit_allowed(s_target_file):
                    shutil.copy2(board_specs.constraints_file, s_target_file)

            ##############################
            # PROJECT CONFIG FILE
            ##############################
            # holds project variables that might be used by multiple tools, and 
            # thus are handy to have one central spot
            # About that idea: Some of the variables in here, like part and 
            # board_part, are actually only used by the vivado project, they 
            # would not be necessary to have in the json file. Also managing 
            # that introduces overhead, because you always have to update the 
            # json file AND the vivado project. And you either need to make 
            # clear that adapting the json file doesn't change the vivado 
            # project - or you need to implement checks between json and vivado 
            # project in the build functions, which is probably what is gonna 
            # happen...
            # Anyway, for some variables it actually makes sense:
            # - hw_target: programming the fpga doesn't need to open a vivado 
            # project, it only fetches the bitstream and whatever it needs.
            # - sim_top: third-party simulators...
            # conclusion: Yes, the project_config file does do actual work in 
            # some situations, and for the rest I justify the overhead with the 
            # fact that it gives you a quick overview on every project variable 
            # that has somewhat of a dynamic character to it.
            if top is not None:
                s_top_module = ""
            else:
                s_top_module = top
            s_target_file = self.PLACEHOLDERS['FILE_PROJECT_CONFIG']
            self.project_config = {
                "project_type": subcommand,
                "part": part,
                "board_part": board_specs.xilinx_board_specifier,
                "top": s_top_module,
                "sim_top": s_top_module,
                "simulator": "xsim",
                "hw_version": "latest",
                "sim_args_modelsim": "",
                "sim_args_questa": "",
                "sim_args_verilator": "",
                "sim_args_xsim": "",
                "sim_verbosity": 2
                }
            if self._check_target_edit_allowed(s_target_file):
                self._write_project_config()

        elif subcommand == "":
            print("You must specify a project platform (xilinx or others)")
        else:
            print(f"Project platform '{subcommand}' unknown")

    def _load_project_config(self):
        """return the contents of the project config json file as a dict
        """
        # (quickly, why do we use json instead of yaml? Answer: it works with 
        # the tcl packages in older vivado versions (namely 2019.1 in the test 
        # case), yaml doesnt. program_fpga makes use of the tcl yaml package, 
        # where in older versions importing a yaml script as a tcl dict didn't 
        # work straightforward when tested. json however, being the older format, 
        # did, so we go with that)
        if os.path.isfile(self.PLACEHOLDERS['FILE_PROJECT_CONFIG']):
            with open(self.PLACEHOLDERS['FILE_PROJECT_CONFIG'], 'r') as f_in:
                self.project_config = json.load(f_in)
        else:
            self.project_config = {}

    def _write_project_config(self):
        with open(self.PLACEHOLDERS['FILE_PROJECT_CONFIG'], 'w') as f_out:
            json.dump(self.project_config, f_out, indent=4)

    def _ext_script_handler(self, submodule, script, symlink=False) -> bool:
        """special file handling:
        * project_config: Don't overwrite an existing project_config. Only add 
        the fields from the project_config in scripts_xilinx that are not 
        already present. (the idea: an extension to the scripts might have added 
        a new project_config variable, like for simulator configuration. But if 
        only the code_manager generated the project_config, that would require 
        a new commit and a whole code_manager update, when actually just 
        updating the scripts repo is much more appropriate. On the other hand, 
        you don't want to overwrite any existing field in the project_config.
        """
        if submodule == "scripts" and script == "project_config":

            self._load_project_config()
            # (by the way, why not self._command_config for the update? Because 
            # that one is meant for editing standard fields, that potentially 
            # require more action than just setting the variable in the 
            # project_config (like the vivado project top) - next to that, it 
            # overwrites existing fields and is explicitly meant to do so)

            file_script = os.path.join(
                    self.git_util.get_path(submodule), "external_files", script)
            with open(file_script, 'r') as f_in:
                d_config_add = json.load(f_in)

            for key, value in d_config_add.items():
                if key not in self.project_config:
                    self.project_config[key] = value

            self._write_project_config()

            return True

        return False

    def _command_config(self, top=None, sim_top=None, part=None, board_part=None,
                        hw_version=None, simulator=None, xil_tool=False,
                        vio_top=None,no_xil_update=False, **kwargs):
        """update the project config file (self.PLACEHOLDERS['FILE_PROJECT_CONFIG']) 
        with the specified parameters
        """

        # the goal: automatically update the config for all non-None arguments
        # problem: 1. how to get the arguments 2. there might be arguments that 
        # refer to this function, but are not project config parameters
        # solution: We use inspect.getargvalues(), which in combination with 
        # pointing to this function as the current frame gives us a list of the 
        # defined function arguments and the ones that are actually passed.  
        # Problem: 'values' uses locals() in the backend, which apparently 
        # somehow is recursive (at least here), so 'values' itself would contain 
        # 'values', endlessly. Since it also contains 'self' and friend, we have 
        # to filter 'values' anyway, then we just incorporate the information 
        # from 'rgas'. We filter that for arguments that:
        # - appear in 'args'
        # - are not 'self'
        # - are not None
        # - are not in the list of non_config_arguments that we define
        non_config_arguments = ['no_xil_update']

        # meaning of xil_project_parameters: those are the ones that play a role 
        # in the xilinx project. So if one of those gets passed, we need to call 
        # the respective API to update the xilinx project.
        xil_project_parameters = ["part", "board_part", "top"]

        frame = inspect.currentframe()
        args, _, _, values = inspect.getargvalues(frame)

        def fun_filter_args(raw_item):
            key, value = raw_item
            if key not in args or key == 'self':
                return False
            if not value:
                return False
            if key in non_config_arguments:
                return False
            return True

        config_args = dict(filter(fun_filter_args, values.items()))

        self._load_project_config()
        update_xil_project = False
        # update config where necessary
        for key, value in config_args.items():
            # catch the case that for some reason the key doesn't exist yet in 
            # the config (shouldn't happen, but might happen)
            try:
                if not self.project_config[key] == value:
                    self.project_config[key] = value
                    # only update xilinx project if the key value has actually 
                    # changed
                    if key in xil_project_parameters:
                        update_xil_project = True
            except KeyError:
                self.project_config[key] = value
                if key in xil_project_parameters:
                    update_xil_project = True

        self._write_project_config()

        # update the vivado project if necessary
        # TODO: maybe there is a more elegant way to select the xilinx tool, but 
        # for now it's good enough to default to vivado
        if not no_xil_update and update_xil_project:
            if not xil_tool:
                xil_tool = "vivado"
            s_tcl_manage_prj = os.path.join(
                self.PLACEHOLDERS['DIR_SCRIPTS_XIL'], self.PLACEHOLDERS['SCRIPT_MANAGE_XIL_PRJ'])
            os.system(f"{xil_tool} -mode batch -source {s_tcl_manage_prj}")

    def _command_testbench(self, module, simulator="generic", flow="sv_class", **kwargs):
        """generate a testbench with an optional parameter to use the template 
        for a specific simulator

        :simulator: if "verilator", instead of a simalutor-agnostic 
        systemverilog testbench environment, creates a verilator testbench 
        enviroment. (FUTURE) also generates necessary simulation scripts and 
        maybe xilinx IP exports for the respective target simulator.
        :flow: test environment type (not every flow is available with every 
        simulator, e.g. the below options have no effect for simulator=verilator)
            * "sv_class": class-based non-UVM systemverilog verification 
            environment
            * (FUTURE) "uvm"
            * (FUTURE) "raw": single-file non-class systemverilog testbench
        """

        if simulator == "generic":

            ##############################
            # MODULE-SPECIFIC
            ##############################

            dir_tb_module = os.path.join(self.PLACEHOLDERS['DIR_TB'], module)
            if not os.path.isdir(dir_tb_module):
                os.mkdir(dir_tb_module)

            s_file_module = os.path.join(
                    self.PLACEHOLDERS['DIR_RTL'], module + ".sv")
            hdl_module_interface = HdlModuleInterface.from_sv(s_file_module)

            # TESTBENCH TOP
            # TODO: dynamic placeholder INST_MODULE
            s_target_file = os.path.join(dir_tb_module, "tb_" + module + ".sv")
            if self._check_target_edit_allowed(s_target_file):

                d_port_connections = hdl_module_interface.port_connections
                for port_name in d_port_connections:
                    if not re.match(r'.*rst.*', port_name):
                        d_port_connections[port_name] = f"if_{module}.{port_name}"
                    else:
                        d_port_connections[port_name] = f"if_rst.{port_name}"
                l_module_inst = hdl_module_interface.instantiate_with_conn(
                        d_port_connections, add_newlines=False)
                s_module_inst = '\n'.join(l_module_inst)

                template_out = self._load_template("tb_sv_module_top", {
                                "MODULE": module,
                                "INST_MODULE": s_module_inst,
                                })
                self._write_template(template_out, s_target_file)

            # MODULE INTERFACE
            s_target_file = os.path.join(dir_tb_module, "ifc_" + module + ".sv")

            if self._check_target_edit_allowed(s_target_file):
                hdl_module_interface.generate_interface_class_sv(
                            include_rst=False, clk_to_ports=True, file_out=s_target_file)

            # MODULE AGENT
            s_target_file = os.path.join(dir_tb_module, "agent_" + module + ".sv")
            if self._check_target_edit_allowed(s_target_file):
                template_out = self._load_template("tb_sv_module_agent", {
                                "MODULE": module,
                                })
                self._write_template(template_out, s_target_file)

        elif simulator == "verilator":

            s_target_file = os.path.join(
                    self.PLACEHOLDERS['DIR_TB'], "tb_vl_" + module + ".cpp")
            if self._check_target_edit_allowed(s_target_file):
                template_out = self._load_template("testbench_verilator", {
                                "MODULE_NAME": module,
                                })
                self._write_template(template_out, s_target_file)

        else:
            print(f"Simulator/Testbench flow {simulator} is not implemented or supported yet")

    def _command_xip_ctrl(self, target=None,
                          print_signal_formats=False, write_user_template=False,
                          **kwargs):
        """invoke XilinxDebugCoreManager to generate vio ctrl IP core target files, 
        based on a set of vio-connection signals.

        :print_signal_formats: If specified, the command only prints the 
        required formats for ila and vio signals, and then exits without any 
        processing.
        :write_user_template: If specified, the command only tries to print the 
        user template to `xip_ctrl/<vio_top>_vio_ctrl.tcl`

        If no target (-t <target>) is specified, the top level module is 
        retrieved from the project config json file, and that file is analysed 
        for generating the vio ctrl IP. A different module can be specified by 
        passing -t <target> (module name, not file name). Then the file for that 
        module is needs to be found in the project's RTL directory.
        """
        # TODO: add to the documentation: How to control the vio? 2 options:
        # 1. via a specific `xip_ctrl/<vio_top>_vio_ctrl.tcl` (with <vio_top> as 
        # specified in project_config)
        # 2. fallback to standard `scripts_xil/vio_ctrl.tcl`
        # Option 1 basically has to import option 2 for the entire API, and then 
        # on top of that can specify its own API. The make command automatically 
        # checks if option 1 is present, and if it isn't, reverts to option 2.
        # --write_user_template generates a skeleton for the option 2 script.

        # TODO: retrieving the top level module file is currently hardcoded to 
        # systemverilog. Be a little more inclusive...

        if print_signal_formats:

            ##############################
            # PRINT SIGNAL FORMATS
            ##############################
            XilinxDebugCoreManager.get_signal_formats(print_output=True)

        elif write_user_template:
            self._load_project_config()
            target_module = self.project_config['vio_top']
            s_target_file = os.path.join(
                    self.PLACEHOLDERS['DIR_XIP_CTRL'], target_module + "_vio_ctrl.tcl")
            if self._check_target_edit_allowed(s_target_file):
                template_out = self._load_template("vio_ctrl_user")
                self._write_template(template_out, s_target_file, create_path=True)

        else:

            ##############################
            # PROCESS MODULE
            ##############################

            if not target:
                self._load_project_config()
                target_module = self.project_config['top']
            else:
                target_module = target

            l_rtl_files = os.listdir(self.PLACEHOLDERS['DIR_RTL'])
            # look for the file in the list of rtl files that matches the 
            # <target_module>.sv. Theoretically, it looks for all files and takes 
            # the first one. But if there is more than one match, then the root of 
            # error is not my sloppy coding.
            # TODO: fix invalid escape sequence warning
            f_match_target_module = lambda x: re.match(target_module + r"\.sv", x)
            s_target_module_file = [
                    i for i in l_rtl_files if bool(f_match_target_module(i))][0]
            s_target_module_path = os.path.join(
                            self.PLACEHOLDERS['DIR_RTL'], s_target_module_file)

            file_vio_ctrl_signals = os.path.join(
                    self.PLACEHOLDERS['DIR_XIP_CTRL'],
                    self.PLACEHOLDERS['FILE_XILINX_VIO_CONTROL_SIGNALS_CONFIG'])

            self.xilinx_debug_core_manager.process_module(
                    s_target_module_path,
                    s_xip_declaration_dir=self.PLACEHOLDERS['DIR_XILINX_IPS'],
                    s_json_file_name_signals=file_vio_ctrl_signals)
