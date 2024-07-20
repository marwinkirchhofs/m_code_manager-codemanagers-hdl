#!/usr/bin/env python3

# supported module declaration syntax (whitespaces optional as per language 
# syntax):
#
# (SYSTEM)VERILOG
#
# module <module_name> #(
# ...
#     ) (
# );
#
# module <module_name> (
# );
#
# - no separate line for opening round bracket
# - parameters are optional
#
# VHDL
# TODO

# TODO: also update the parameter list

import re


class HdlPort(object):

    # TODO: maybe it's more logical to inherit from this class in sv/vhdl code 
    # managers

    PORT_IN         = "input"
    PORT_OUT        = "output"
    PORT_INOUT      = "inout"

    # (doesn't work as a @property, because it's a classmethod. combining both 
    # apparently used to be possible, but is deprecated in python>3.12 or so)
    @classmethod
    def port_directions(cls):
        return [cls.PORT_IN, cls.PORT_OUT, cls.PORT_INOUT]

    # the re can not detect signal width in certain cases, but it should still 
    # correctly detect the port name and direction:
    # - multi-dimensional array
    # - parameterized (non-digit) width
    # - unpacked arrays
    #
    # setup for detecting multi-dimensional array in the future: the RE matches 
    # an arbitrary number of width declarations ('[...:...]'), both for packed 
    # and unpacked. The width per dimension can be retrieved by findall on the 
    # respective match groups

    # TODO: due to the ()* groups, the re accepts wrong syntax like '[N-1:0' 
    # - no problem if things are coded correctly, but it would be nice to fix 
    # that

#     # match [PAR-1:0][3:1]...
#     __re_sig_multi_dim_sv = r'((\[[\w+\+\-\*\/]+:[\w+\+\-\*\/]+\])\s*)*'
#     # put it together for full line
#     __re_port_decl_sv = \
#         re.compile(r'\s*(input|output|inout)\s+(logic|reg|wire){0,1}\s+'
#                    + __re_sig_multi_dim_sv + r'(\w+)\s*' + __re_sig_multi_dim_sv
#                    + r',{0,1}\s*')
    __re_sig_single_dim_sv = r'\[[\w+\+\-\*\/]+:[\w+\+\-\*\/]+\]'
    __re_sig_multi_dim_sv = r'((' + __re_sig_single_dim_sv + ')*)'
    __re_port_decl_sv = \
            re.compile(r'\s*(input|output|inout)\s+((logic|reg|wire){0,1}\s+)'
               + __re_sig_multi_dim_sv + r'\s*(\w+)\s*' + __re_sig_multi_dim_sv
               + r',{0,1}\s*')

    def __init__(self, name, width=1, direction=PORT_OUT, dimensions = None):
        """
        :direction: one of HdlPort.PORT_* (default: PORT_OUT)
        :dimensions: dictionary with keys "packed" and "unpacked", both items 
        lists of plain-text dimension specifiers ("[...:...]")
        """
        # TODO: dimensions might need to be represented in a way that also works 
        # for vhdl, so far it is plain systemverilog syntax. On the other hand, 
        # multi-dim in vhdl is an array in the first place...
        self.name = name
        self.width = width
        self.direction = direction
        if not dimensions:
            self.dimensions = {
                    "packed": [],
                    "unpacked": [],
                    }
        else:
            self.dimensions = dimensions

    @classmethod
    def __from_port_decl_mo(cls, match_obj, lang="sv"):
        """
        :match_obj: match object retrieved by __re_port_decl_*
        :lang: sv or vhdl
        """
        if lang == "sv":
            if not match_obj:
                return None
            name = match_obj.group(6)
            direction = match_obj.group(1)
            dimensions = {
                    "packed": re.findall(cls.__re_sig_single_dim_sv, match_obj.group(4)),
                    "unpacked": re.findall(cls.__re_sig_single_dim_sv, match_obj.group(7)),
                    }

            # TODO: couldn't you do this more elegant, with the port types as 
            # a dictionary and then access to PORT_* with @property?
            if not direction in cls.port_directions():
                raise Exception(f"Invalid signal direction: {direction}")

            # TODO: handle the width, as soon as you have a suitable data 
            # structure for that
            return cls(name, width=-1, direction=direction, dimensions=dimensions)

        else:
            raise Exception(f"Support for {lang} port declaration match objects "
                            "not implemented")

    @classmethod
    def from_sv(cls, line):
        """
        :line: line of code (within a module declaration)
        """
        match_obj = cls.__re_port_decl_sv.match(line)
        return cls.__from_port_decl_mo(match_obj, "sv")

    def to_member_signal_sv(self):
        """
        prints out the port as a member signal declaration
        
        EXAMPLE:
        name = "my_port", direction = "out", dimensions...
        ->
        "logic <dimensions packed> my_port <dimensions unpacked>;"
        """
        
        s_out = ""
        s_out = s_out + f"logic"
        if self.dimensions["packed"]:
            s_out = s_out + " "
            for s_dim in self.dimensions["packed"]:
                s_out = s_out + s_dim
        s_out = s_out + f" {self.name}"
        if self.dimensions["unpacked"]:
            s_out = s_out + " "
            for s_dim in self.dimensions["unpacked"]:
                s_out = s_out + s_dim
        s_out = s_out + ";"
        return s_out


class HdlModuleInterface(object):

    ##############################
    # REGEX
    ##############################

    # MODULE DECLARATION
    
    # distinct between parameterized and parameter-free declaration via the 
    # regex
    # match "module <name> ("
    __re_begin_module_decl_sv_param = \
        re.compile(r'\s*module\s+(\w+)\s*#\(\s*')
    # match "module <name> #("
    __re_begin_module_decl_sv_no_param = \
        re.compile(r'\s*module\s+(\w+)\s*\(\s*')
    # match "    ) ("
    __re_module_decl_sv_param_end = \
        re.compile(r'\s*\)\s*\(\s*')
    # match ");"
    __re_module_decl_sv_end = \
        re.compile(r'\s*\)\s*;\s*')

    # MODULE INSTANTIATION
    __re_begin_module_inst_sv_param = \
            re.compile(r'\s*(\w+)\s*#\(\s*')
    __re_begin_module_inst_sv_no_param = \
            re.compile(r'\s*(\w+)\s*(\w+)\s*\(\s*')
    __re_module_inst_sv_param_end = \
            re.compile(r'\s*\)\s*(\w+)\s*\(\s*')
    __re_module_inst_sv_end = \
            re.compile(r'\s*\)\s*;\s*')
    __s_module_inst_sv_connected_signal = \
            r'\w+(\[[\w+\+\-\*\/\:]+\])*'
    __re_module_inst_sv_port_conn = \
            re.compile(r'\s*\.(\w+)\s*\(\s*('
                       + __s_module_inst_sv_connected_signal + r')*\s*\),{0,1}\s*')
    __re_module_inst_sv_end_module = \
            re.compile(r'\s*endmodule\s*(//.*)*')

    INST_PREFIX = "inst_"

    def __init__(self, name, ports=[]):
        """
        :ports: list of HdlPort objects
        """
        self.name = name
        self.ports = ports

    @property
    def port_connections(self):
        return dict.fromkeys([x.name for x in self.ports], "")

    @classmethod
    def from_sv(cls, declaration):
        """assumes that only one module is declared in declaration. (If there 
        are multiple, the first one is detected)

        :declaration: can be one of 2 options:
            1. str - file name to SystemVerilog module file
            2. list of str - lines of code that contains a SystemVerilog module 
            declaration
        """

        if isinstance(declaration, str):
            with open(declaration, 'r') as f_in:
                l_lines = f_in.readlines()
        else:
            l_lines = declaration

        in_ports_decl = False
        in_param_decl = False

        for line in l_lines:
            if not in_ports_decl and not in_param_decl:
                # check for module declaration begin (first non-parameterized 
                # module, then parameterized module)
                mo = cls.__re_begin_module_decl_sv_no_param.match(line)
                if mo:
                    in_ports_decl = True
                    module_name = mo.group(1)
                    l_module_ports = []

                mo = cls.__re_begin_module_decl_sv_param.match(line)
                if mo:
                    in_param_decl = True
                    module_name = mo.group(1)
                    l_module_ports = []

            elif in_param_decl:
                mo = cls.__re_module_decl_sv_param_end.match(line)
                if mo:
                    in_param_decl = False
                    in_ports_decl = True

            else:
                mo = cls.__re_module_decl_sv_end.match(line)
                if mo:
                    # if module declaration end detected, finish reading and 
                    # return
                    in_ports_decl = False
                    return cls(module_name, l_module_ports)
                else:
                    # if no module declaration detected, detect ports in line
                    port = HdlPort.from_sv(line)
                    if port:
                        l_module_ports.append(port)

        # return None if no module declaration was detected
        return None

    def __detect_module_inst_begin(self, line):
        """
        :line: str - line of code to match for the instantiation

        :returns: None if no match, or the type of match: "param" for 
        a parameterized instantiation, "no_param" for a non-parameterized 
        instantiation (also returns "no_param" if the end of a parameterization 
        was detected, thus "no_param" always indicates the start of the port 
        list
        """
        re_begin_module_inst_sv_param = \
                re.compile(r'\s*' + self.name + r'\s*#\(\s*')
        re_begin_module_inst_sv_no_param = \
            re.compile(r'\s*' + self.name + r'\s*'
                    + self.INST_PREFIX + self.name + r'\s*\(\s*')
        re_module_inst_sv_param_end = \
                re.compile(r'\s*\)\s*'+self.INST_PREFIX+self.name+r'\s*\(\s*')

        if re_begin_module_inst_sv_param.match(line):
            return "param"
        if re_begin_module_inst_sv_no_param.match(line):
            return "no_param"
        if re_module_inst_sv_param_end.match(line):
            return "no_param"
        return None


    def update_instantiation(self, destination, overwrite=True, no_create=False):
        """Updates or creates in instantiation in a given module file. Any 
        instantiation that is found is updated in-place. "Updating" means that 
        the list of ports is updated from self.ports. Any connection to a port 
        is preserved in the instantiation. If no instantiation is found at all, 
        one instantiation with empty connections is generated at the end of the 
        module. It is expected that destination only holds one module 
        definition.

        Both parameterized and non-parameterized instantiations are supported.  
        The following syntax is required for an instantiation to be detected (in 
        terms of which symbol on which line, whitespaces don't matter):

        <module> #(
        ...
        ) <inst_name> (
        );

        <module> <inst_name> (
        ...
        );

        Anything else will not be detected.

        :destination: file path indicating where to update/create the 
        instantiation
        :overwrite: (not implemented) if True, an existing instantiation will be 
        overwritten in-place (existing signal connections are still preserved).  
        If False, the existing instantiation will instead be commented out, and 
        the updated version be placed below.
        """

        # TODO: implement overwrite option

        # TODO: add sort of a "reverse" option: for a given file, update all the 
        # module instantiations in that file. Because then you can just do that 
        # to your entire codebase (ok, maybe that's useless)

        with open(destination, 'r') as f_in:
            l_lines = f_in.readlines()

        l_lines_out = []

        # for every module port, this dict can hold an existing signal 
        # connection name
        d_port_connections = dict.fromkeys([x.name for x in self.ports], "")

        in_port_list = False
        in_param_list = False
        # indicate that destination contains at least one instantiation
        inst_created = False

        for line in l_lines:

            mo = self.__re_module_inst_sv_end_module.match(line)
            if mo:
                if not inst_created and not no_create:
                    # (also works without having read anything, because 
                    # d_port_connections is derived from the known ports of self)
                    l_lines_out.append(
                            f"{self.name} {self.INST_PREFIX}{self.name} (\n")
                    l_lines_out.extend(self.instantiate_with_conn(d_port_connections))
                    l_lines_out.append(");\n")
                    l_lines_out.append("\n")

                # don't forget to add the 'endmodule' line no matter what
                l_lines_out.append(line)
            elif not (in_port_list or in_param_list):
                l_lines_out.append(line)
                if self.__detect_module_inst_begin(line) == "no_param":
                    in_port_list = True
                elif self.__detect_module_inst_begin(line) == "param":
                    in_param_list = True
            elif in_param_list:
                l_lines_out.append(line)
                if self.__detect_module_inst_begin(line) == "no_param":
                    in_param_list = False
                    in_port_list = True
            elif in_port_list:
                mo = self.__re_module_inst_sv_end.match(line)
                if mo:
                    in_port_list = False
                    l_lines_out.extend(self.instantiate_with_conn(d_port_connections))
                    l_lines_out.append(line)
                    inst_created = True

                # idea: iterate through the existing instantiation, and for 
                # every signal that you find that (still) exists in the module 
                # interface, register the connected signal, if there is one, in 
                # d_port_connections. Afterwards compile the new instantiation 
                # (instead of doing it in-place line-by-line)
                mo = self.__re_module_inst_sv_port_conn.match(line)
                if mo:
                    # module connection found
                    module_name = mo.group(1)
                    conn_name = mo.group(2)
                    
                    try:
                        # fails if module_name is not a known port, in which 
                        # case module_name should be removed from the 
                        # instantiation anyway
                        if conn_name:
                            d_port_connections[module_name] = conn_name
                    except KeyError:
                        pass

        with open(destination, 'w') as f_out:
            f_out.writelines(l_lines_out)

    def generate_interface_class_sv(self, include_rst=False, clk_to_ports=True,
                                    file_out=None):
        """
        turn the module interface into a systemverilog interface class.

        :include_rst: if False, any signal matching *rst* is excluded from the 
        interface. That helps with utilizing the interface in a testbench 
        environment which handles resets in a separate way
        :clk_to_ports: if True, signals matching *clk* will be converted into 
        inputs to the interface, instead of members. Tries to match the 
        "standard" way that an interface is set up.
        :file_out: if not None, the interface is written out to file_out (any 
        contents are overwritten without asking)

        :returns: list of strings with the lines of code describing the 
        interface (no '\n' termination)
        """
        
        l_lines_out = []

        # DECLARATION, CLOCKS
        if clk_to_ports:
            l_lines_out.append(f"interface ifc_{self.name} (")
            for port in filter(lambda x: re.match(r'.*clk.*', x.name), self.ports):
                l_lines_out.append(f"        input {port.name},")
            # remove trailing ',' from last line (also works if no *clk* was found, 
            # in that case just pops and appends again the first line)
            s = l_lines_out.pop()
            l_lines_out.append(s.replace(',',''))

            l_lines_out.append(");")
        else:
            l_lines_out.append(f"interface ifc_{self.name};")

        l_lines_out.append("")

        # MEMBER SIGNALS
        if clk_to_ports and include_rst:
            filter_fun = lambda x: not re.match(r'.*clk.*', x.name)
        elif (not clk_to_ports) and include_rst:
            filter_fun = lambda x: x.name
        elif clk_to_ports and (not include_rst):
            filter_fun = lambda x: \
                    not re.match(r'.*clk.*', x.name) and \
                    not re.match(r'.*rst.*', x.name)
        else:
            filter_fun = lambda x: not re.match(r'.*rst.*', x.name)

        for port in filter(filter_fun, self.ports):
            l_lines_out.append("    " + port.to_member_signal_sv())

        l_lines_out.append("")

        # TODO: are modports needed for anything here? I mean, it's 
        # a simulation-only interface, you should probably just know which 
        # signals you are driving and SOME tool should warn about multi-drivers

        l_lines_out.append("endinterface")

        if file_out:
            with open(file_out, 'w') as f_out:
                f_out.writelines([s+'\n' for s in l_lines_out])

    @staticmethod
    def instantiate_with_conn(d_port_connections, add_newlines=True):
        """
        Print an instantiation for a module with connections for the ports.

        :d_port_connections: dictionary with port names as keys and connections 
        as values. Can be created and afterwards filled with:
        dict.fromkeys([x.name for x in self.ports], "")
        :add_newlines: adds a line break ('\n') to every line
        :returns: list of strings
        """

        s_endline = '\n' if add_newlines else ''
        l_lines_out = []
        for port, conn in d_port_connections.items():
            l_lines_out.append(f"    .{port} ({conn})," + s_endline)
            # TODO: ensure proper bracket alignment
            # TODO: preserve leading whitespaces (e.g. higher 
            # indentation in generate blocks)
        # remove ',' from last port-connection
        s_last_line = l_lines_out.pop()
        l_lines_out.append(s_last_line.replace(',',''))

        return l_lines_out


        


