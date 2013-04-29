import sys
import warnings
import argparse
from collections import OrderedDict
from xml.etree.ElementTree import Element, SubElement, tostring, parse
from xml.dom.minidom import parseString

# # lxml's interface is almost the same as xml's but you can order element attribues with it
# # (not that you should do it but it's still nice to see parameter name as first attribute
# # for readability). But as lxml is not in the standard library I'll just leave its traces
# # around (search for LXML) if someone wants to use it.
# from lxml.etree import Element, SubElement, tostring, parse


class _NumericRange(object):
    def __init__(self, n_type, n_min=None, n_max=None):
        self.n_type = n_type
        self.n_min = n_min
        self.n_max = n_max

    def argparse_type(self):
        def is_in_range(value):
            value = self.n_type(value)  # TODO: do we need a warning if 5.6 gets cast to 5?
            if self.n_min is not None and value < self.n_min:
                raise ValueError("number is below minimum")
            if self.n_max is not None and value > self.n_max:
                raise ValueError("number is above maximum")
            return value
        # we'll pass this function handle to argparse's `type` option that not only casts input as it
        # would normally but also performs a range check and stalls parsing if value is illegal
        return is_in_range

    def ctd_range_string(self):
        n_min = str(self.n_min) if self.n_min is not None else ''
        n_max = str(self.n_max) if self.n_max is not None else ''
        return '%s:%s' % (n_min, n_max)


class _FileFormat(object):
    def __init__(self, formats):
        self.formats = formats

    def argparse_type(self):
        def legal_formats(filename):
            # os.path.splitext(filename)[1][1:] wouldn't handle *.fastq.gz or any double-extension
            for format in self.formats:
                if filename.endswith('.' + format):  # TODO: should we be lenient with letter case?
                    return filename
            else:
                raise ValueError("File extension not in %s." % '/'.join(self.formats))
        # similarly to NumericRange, this function object will perform argparse's type enforcing
        # w/ a filename extension checking step. One could even implement MIME-type checking here
        return legal_formats

    def ctd_format_string(self):
        return ','.join(('*.' + format for format in self.formats))


class ArgumentItem(object):
    def __init__(self, name, **kwargs):
        self.name = name
        self.type = kwargs.get('type', str)
        self.tags = kwargs.get('tags', [])
        self.required = kwargs.get('required', False)
        self.description = kwargs.get('description', '')
        self.is_list = kwargs.get('is_list', False)

        default = kwargs.get('default', None)
        # enforce that default is the correct type if exists. Elementwise for lists
        self.default = None if default is None else map(self.type, default) if self.is_list else self.type(default)
        # same for choices. I'm starting to think it's really unpythonic and we should trust input. TODO
        choices = kwargs.get('choices', None)
        self.choices = None if choices is None else map(self.type, choices)

        # Default value should exist IFF argument is not required.
        # TODO: if we can have optional list arguments they don't have to have a default? (empty list)
        if self.required:
            assert self.default is None, ('Required field `%s` has default value' % self.name)
        else:
            assert self.default is not None, ('Optional field `%s` has no default value' % self.name)

        self.restrictions = None
        if 'num_range' in kwargs:
            self.restrictions = _NumericRange(self.type, *kwargs['num_range'])
        elif 'file_formats' in kwargs:
            self.restrictions = _FileFormat(kwargs['file_formats'])

    def argparse_call(self):
        # return a dictionary to be keyword-fed to argparse's add_argument(name, **kws).
        kws = {}
        if self.is_list:
            kws['nargs'] = '+'  # TODO: maybe allow '?' if not required [see required vs default above]

        kws['help'] = self.description
        kws['required'] = self.required

        # we'll handle restrictions (numeric ranges & file formats) in argparse's type casting
        # step. So we don't run the values through int() but a function that checks values and
        # only casts to int if it range criteria are met. argparse_type() returns this function.
        kws['type'] = self.type if self.restrictions is None else self.restrictions.argparse_type()

        if self.choices is not None:
            kws['choices'] = self.choices
        if self.default is not None:
            kws['default'] = self.default

        # if we take explicit metavar definition away we run into http://bugs.python.org/issue11874
        # I don't exactly know why but it's an argparse bug for sure. Really strange.
        # Actually it's a good idea to not have those long group1:group2:... parts there anyway.
        # TODO: maybe allow setting it manually. Like having a self.etc dictionary where users
        # can pass further keyword arguments to argparse for full customization.
        kws['metavar'] = self.name.upper()
        return kws

    def xml_node(self):
        # name, value, type, description, tags, restrictions, supported_formats
        attribs = OrderedDict()
        attribs['name'] = self.name
        if not self.is_list:
            attribs['value'] = '' if self.default is None else str(self.default)
        attribs['type'] = {int: 'int', float: 'float', str: 'string'}[self.type]
        attribs['description'] = self.description
        attribs['tags'] = ','.join(self.tags)

        if self.choices is not None:
            attribs['restrictions'] = ','.join(self.choices)
        elif isinstance(self.restrictions, _NumericRange):
            attribs['restrictions'] = self.restrictions.ctd_range_string()
        elif isinstance(self.restrictions, _FileFormat):
            attribs['supported_formats'] = self.restrictions.ctd_format_string()

        if self.is_list:
            top = Element('ITEMLIST', attribs)
            if self.default is not None:
                for d in self.default:
                    SubElement(top, 'LISTITEM', {'value': str(d)})
            return top
        else:
            return Element('ITEM', attribs)

    def append_argument(self, argparse_root, argparse_current, base_name, is_root=False):
        argparse_current.add_argument(base_name, **self.argparse_call())
        # print "-----ARGUMENT ADDED:", base_name, self.argparse_call()  # debug


class ArgumentGroup(object):
    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.arguments = OrderedDict()

    def add(self, name, **kwargs):
        if name in self.arguments:
            warnings.warn('Name `%s` in subsection `%s` defined twice! Overriding first')

        self.arguments[name] = ArgumentItem(name, **kwargs)

    def add_group(self, name, description=""):
        if name in self.arguments:
            warnings.warn('Name `%s` in subsection `%s` defined twice! Overriding first')

        self.arguments[name] = ArgumentGroup(name, description)
        return self.arguments[name]

    def xml_node(self):
        top = Element('NODE', {'name': self.name, 'description': self.description})
        # TODO: if an ArgumentItem comes after an ArgumentGroup, the CTD won't validate.
        # Of course this should never happen if the argument tree is built properly but it would be
        # nice to take care of it if a user happens to randomly define his arguments and groups.
        # So first we could sort self.arguments (Items first, Groups after them).
        for arg in self.arguments.itervalues():
            top.append(arg.xml_node())
        return top

    def append_argument(self, argparse_root, argparse_current, base_name, is_root=False):
        # argparse is buggy and won't display help messages for arguments that are doubly nested in
        # groups (although it parses them perfectly). So while it's possible and totally legal, one
        # should never call add_argument_group() on groups because it will ruin his help message
        # display. So we'll have to append all groups to the main parser needing this ugly hack
        # of keeping argparse_root and argparse_current objects side by side so nested groups can
        # always access the main parser and arguments can access their parent group.

        # arguments in subsections are named -subsection1:subsection2:argument in command line
        # so we need colon separated argument naming in non-top-level arguments.
        colon = '' if is_root else ':'
        argparse_current = argparse_root.add_argument_group(self.name, self.description)
        for name, arg in self.arguments.iteritems():
            arg.append_argument(argparse_root, argparse_current, '%s%s%s' % (base_name, colon, name), is_root=False)


class CTDopts(object):
    def __init__(self, name, version, **kwargs):
        self.name = name
        self.version = version
        self.optional_attribs = kwargs  # description, manual, docurl, category (+executable stuff).
        self.main_node = ArgumentGroup('1', 'Instance "1" section for %s' % self.name)  # OpenMS legacy?

    def get_root(self):
        return self.main_node

    def write_ctd(self):
        tool = Element('tool')

        # we do this ugly thing because the CTD schema is a bit weird in expecting a required
        # <version> element in the middle of the below list of optional elements.
        opt_elements_1 = ['executableName', 'executablePath']  # after this comes 'version'
        opt_elements_2 = ['description', 'manual', 'docurl', 'category']

        SubElement(tool, 'name').text = self.name
        for oo in opt_elements_1:
            if oo in self.optional_attribs:
                SubElement(tool, oo).text = self.optional_attribs[oo]
        SubElement(tool, 'version').text = self.version
        for oo in opt_elements_2:
            if oo in self.optional_attribs:
                SubElement(tool, oo).text = self.optional_attribs[oo]

        # # LXML SYNTAX
        # # again so ugly, but lxml is strict w/ namespace attrib. generation, you can't just add them
        # xsi = 'http://www.w3.org/2001/XMLSchema-instance'
        # params = SubElement(tool, 'PARAMETERS', {
        #     'version': '1.4',
        #     '{%s}noNamespaceSchemaLocation' % xsi: "http://open-ms.sourceforge.net/schemas/Param_1_4.xsd"},
        #     nsmap={'xsi': xsi})

        # XML.ETREE SYNTAX
        params = SubElement(tool, 'PARAMETERS', {
            'version': '1.4',
            'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
            'xsi:noNamespaceSchemaLocation': "http://open-ms.sourceforge.net/schemas/Param_1_4.xsd"})


        # This seems to be some OpenMS hack (defining name, description, version for the second
        # time) but I'll stick to it for consistency
        top_node = SubElement(params, 'NODE',
            name=self.name,
            description=self.optional_attribs.get('description', '')  # desc. is optional, may not have been set
            )

        SubElement(top_node, 'ITEM',
            name='version',
            value=self.version,
            type='string',
            description='Version of the tool that generated this parameters file.',
            tags='advanced'
            )

        # all the above was boilerplate, now comes the actual parameter tree generation
        args_top_node = self.main_node.xml_node()
        top_node.append(args_top_node)

        # # LXML w/ pretty print syntax
        # return tostring(tool, pretty_print=True, xml_declaration=True, encoding="UTF-8")

        # xml.etree syntax (no pretty print available, so we use xml.dom.minidom stuff)
        return parseString(tostring(tool, encoding="UTF-8")).toprettyxml()

    def _register_parameter(self, element, base_name, is_root=False):
        colon = '' if is_root else ':'
        full_name = '%s%s%s' % (base_name, colon, element.attrib['name'])
        if element.tag == 'ITEM':
            self.ini_params[full_name] = [element.attrib['value']]
        elif element.tag == 'ITEMLIST':
            self.ini_params[full_name] = [listitem.attrib['value'] for listitem in element]
        elif element.tag == 'NODE':
            for child in element:
                self._register_parameter(child, full_name, is_root=False)

    def read_ini(self, ini_file):
        ini = parse(ini_file)
        parameters = ini.getroot().find('NODE').find('NODE')

        self.ini_params = OrderedDict()

        for child in parameters:
            self._register_parameter(child, '-', is_root=True)

        # as range/file format/vocabulary checkers are already embedded in the argparse parser object
        # we can just generate the equivalent command line call quick&dirty and let argparse handle it.
        command_line = []
        for arg_name, values in self.ini_params.iteritems():
            command_line.append(arg_name)
            command_line.extend(values)

        # print 'INI file's equivalent command line call:\n', ' '.join(command_line)  # debug
        return command_line

    def parse_args(self, *args):

        # although argparse supports mutually exclusive arguments, it doesn't support argument groups
        # in mutexes. What we want is a mutually exclusive -write_ctd vs -load_ini vs full-fledged
        # commandline and since the latter part is an argument group, we have to find a way around
        # it ourselves. So we have a pre-parsing step where we check whether -write_ctd or -load_ini
        # was called, handle them if so, and if none of them were called we continue with regular
        # command line behaviour.

        preparser = argparse.ArgumentParser()
        preparser.add_argument('-write_ctd', action='store_true')
        preparser.add_argument('-load_ini', type=str)
        ctd_or_ini, rest = preparser.parse_known_args(*args)

        if ctd_or_ini.write_ctd:
            with open(self.name + '.ctd', 'w') as f:
                f.write(self.write_ctd())
                print "%s.ctd written to current directory successfully. Exiting." % self.name
                sys.exit()
        else:
            # if -load_ini was called, we create the argument list from the ini file.
            # if it was not called, we fall back to command line arguments.
            final_args = self.read_ini(ctd_or_ini.load_ini) if ctd_or_ini.load_ini is not None else rest

            regular_parser = argparse.ArgumentParser()
            # we populate an argparse parser with the attributes defined in the CTDopts object...
            self.main_node.append_argument(regular_parser, regular_parser, '-', is_root=True)
            # ...and parse our INI/commandline arguments
            return regular_parser.parse_args(final_args)
