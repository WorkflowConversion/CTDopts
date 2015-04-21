import argparse
from collections import OrderedDict, Mapping
from itertools import chain
from xml.etree.ElementTree import Element, SubElement, tostring, parse
from xml.dom.minidom import parseString
import warnings

# dummy classes for input-file and output-file CTD types.


class _InFile(str):
    """Dummy class for input-file CTD type. I think most users would want to just get the file path
    string but if it's required to open these files for reading or writing, one could do it in these
    classes in a later release. Otherwise, it's equivalent to str with the information that we're
    dealing with a file argument.
    """
    pass


class _OutFile(str):
    """Same thing, a dummy class for output-file CTD type."""
    pass


# module globals for some common operations (python types to CTD-types back and forth)
TYPE_TO_CTDTYPE = {int: 'int', float: 'float', str: 'string', bool: 'boolean',
                   _InFile: 'input-file', _OutFile: 'output-file'}
CTDTYPE_TO_TYPE = {'int': int, 'float': float, 'double': float, 'string': str, 'boolean': bool,
                   'input-file': _InFile, 'output-file': _OutFile, int: int, float: float, str: str,
                   bool: bool, _InFile: _InFile, _OutFile: _OutFile}
PARAM_DEFAULTS = {'advanced': False, 'required': False, 'restrictions': None, 'description': None,
                  'supported_formats': None, 'tags': None}  # unused. TODO.
# a boolean type caster to circumvent bool('false')==True when we cast CTD 'value' attributes to their correct type
CAST_BOOLEAN = lambda x: bool(x) if not isinstance(x, str) else (x in ('true', 'True', '1'))


# Module-level functions for querying and manipulating argument dictionaries.
def get_nested_key(arg_dict, key_list):
    """Looks up a nested key in an arbitrarily nested dictionary. `key_list` should be an iterable:

    get_nested_key(args, ['group', 'subgroup', 'param']) returns args['group']['subgroup']['param']
    """
    key_list = [key_list] if isinstance(key_list, str) else key_list  # just to be safe.
    res = arg_dict
    for key in key_list:
        res = res[key]
    else:
        return res


def set_nested_key(arg_dict, key_list, value):
    """Inserts a value into an arbitrarily nested dictionary, creating nested sub-dictionaries on
    the way if needed:

    set_nested_key(args, ['group', 'subgroup', 'param'], value) sets args['group']['subgroup']['param'] = value
    """
    key_list = [key_list] if isinstance(key_list, str) else key_list  # just to be safe.
    res = arg_dict
    for key in key_list[:-1]:
        if key not in res:
            res[key] = {}  # OrderedDict()
        res = res[key]
    else:
        res[key_list[-1]] = value


def flatten_dict(arg_dict, as_string=False):
    """Creates a flattened dictionary out of a nested dictionary. New keys will be tuples, with the
    nesting information. Ie. arg_dict['group']['subgroup']['param1'] will be
    result[('group', 'subgroup', 'param1')] in the flattened dictionary.

    `as_string` joins the nesting levels into a single string with a semicolon, so the same entry
    would be under result['group:subgroup:param1']
    """
    result = {}

    def flattener(subgroup, level):
        # recursive closure that accesses and modifies result dict and registers nested elements
        # as it encounters them
        for key, value in subgroup.iteritems():
            if isinstance(value, Mapping):  # collections.Mapping instead of dict for generality
                flattener(value, level + [key])
            else:
                result[tuple(level + [key])] = value

    flattener(arg_dict, [])
    if as_string:
        return {':'.join(keylist): value for keylist, value in result.iteritems()}
    else:
        return result


def override_args(*arg_dicts):
    """Takes any number of (nested or flat) argument dictionaries and combines them, giving preference
    to the last one if more than one have the same entry. Typically would be used like:

    combined_args = override_args(args_from_ctd, args_from_commandline)
    """
    overridden_args = dict(chain(*(flatten_dict(d).iteritems() for d in arg_dicts)))
    result = {}
    for keylist, value in overridden_args.iteritems():
        set_nested_key(result, keylist, value)
    return result


def _translate_ctd_to_param(attribs):
    """Translates a CTD <ITEM> or <ITEMLIST> XML-node's attributes to keyword arguments that Parameter's
    constructor expects. One should be able to call Parameter(*result) with the output of this function.
    For list parameters, adding is_list=True and getting <LISTITEM> values is needed after translation,
    as they are not stored as XML attributes.
    """

    # right now value is a required field, but it shouldn't be for required parameters.
    if 'value' in attribs:  # TODO 1_6_3, this line will be deleted.
        attribs['default'] = attribs.pop('value')  # rename 'value' to 'default' (Parameter constructor takes 'default')

    if 'supported_formats' in attribs:  # supported_formats in CTD xml is called file_formats in CTDopts
        attribs['file_formats'] = attribs.pop('supported_formats')  # rename that attribute too

    if 'restrictions' in attribs:  # find out whether restrictions are choices ('this,that') or numeric range ('3:10')
        if ',' in attribs['restrictions']:
            attribs['choices'] = attribs['restrictions'].split(',')
        elif ':' in attribs['restrictions']:
            n_min, n_max = attribs['restrictions'].split(':')
            n_min = None if n_min == '' else n_min
            n_max = None if n_max == '' else n_max
            attribs['num_range'] = (n_min, n_max)
        else:
            raise ModelParsingError("Invalid restriction [%s]. \nMake sure that restrictions are either comma separated value lists or \ncolon separated values to indicate numeric ranges (e.g., 'true,false', '0:14', '1:', ':2.8')" % attribs['restrictions'])

    # TODO: advanced. Should it be stored as a tag, or should we extend Parameter class to have that attribute?
    # what we can do is keep it as a tag in the model, and change Parameter._xml_node() so that if it finds
    # 'advanced' among its tag-list, make it output it as a separate attribute.
    return attribs


class ArgumentError(Exception):
    """Base exception class for argument related problems.
    """
    def __init__(self, parameter):
        self.parameter = parameter
        self.param_name = ':'.join(self.parameter.get_lineage(name_only=True))


class ArgumentMissingError(ArgumentError):
    """Exception for missing required arguments.
    """
    def __init__(self, parameter):
        super(ArgumentMissingError, self).__init__(parameter)

    def __str__(self):
        return 'Required argument %s missing' % self.param_name


class ArgumentTypeError(ArgumentError):
    """Exception for arguments that can't be casted to the type defined in the model.
    """
    def __init__(self, parameter, value):
        super(ArgumentTypeError, self).__init__(parameter)
        self.value = value

    def __str__(self):
        return "Argument %s is of wrong type. Expected: %s, got %s" % (
            self.param_name, TYPE_TO_CTDTYPE[self.parameter.type], self.value)


class ArgumentRestrictionError(ArgumentError):
    """Exception for arguments violating numeric, file format or controlled vocabulary restrictions.
    """
    def __init__(self, parameter, value):
        super(ArgumentRestrictionError, self).__init__(parameter)
        self.value = value

    def __str__(self):
        return 'Argument restrictions for %s failed. Restriction: %s. Value: %s' % (
            self.param_name, self.parameter.restrictions.ctd_restriction_string(), self.value)


class ModelError(Exception):
    """Exception for errors related to CTDModel building
    """
    def __init__(self):
        super(ModelError, self).__init__()


class ModelParsingError(ModelError):
    """Exception for errors related to CTD parsing
    """
    def __init__(self, message):
        super(ModelParsingError, self).__init__()
        self.message = message
        
    def __str__(self):
        return "An error occurred while parsing the CTD file: %s" % self.message
    
    def __repr__(self):
        return str(self)


class UnsupportedTypeError(ModelError):
    """Exception for attempting to use unsupported types in the model
    """
    def __init__(self, wrong_type):
        super(UnsupportedTypeError, self).__init__()
        self.wrong_type = wrong_type

    def __str__(self):
        return 'Unsupported type encountered during model construction: %s' % self.wrong_type


class DefaultError(ModelError):
    def __init__(self, parameter):
        super(DefaultError, self).__init__()
        self.parameter = parameter

    def __str__(self):
        pass


class _Restriction(object):
    """Superclass for restriction classes (numeric, file format, controlled vocabulary).
    """
    def __init__(self):
        pass

    # if Python had virtual methods, this one would have a _single_check() virtual method, as all
    # subclasses have to implement for check() to go through. check() expects them to be present,
    # and validates normal and list parameters accordingly.
    def check(self, value):
        """Checks whether `value` satisfies the restriction conitions. For list parameters it checks
        every element individually.
        """
        if isinstance(value, list):  # check every element of list (in case of list parameters)
            return all((self._single_check(v) for v in value))
        else:
            return self._single_check(value)


class _NumericRange(_Restriction):
    """Class for numeric range restrictions. Stores valid numeric ranges, checks values against
    them and outputs CTD restrictions attribute strings.
    """
    def __init__(self, n_type, n_min=None, n_max=None):
        super(_NumericRange, self).__init__()
        self.n_type = n_type
        self.n_min = self.n_type(n_min) if n_min is not None else None
        self.n_max = self.n_type(n_max) if n_max is not None else None

    def ctd_restriction_string(self):
        n_min = str(self.n_min) if self.n_min is not None else ''
        n_max = str(self.n_max) if self.n_max is not None else ''
        return '%s:%s' % (n_min, n_max)

    def _single_check(self, value):
        if self.n_min is not None and value < self.n_min:
            return False
        elif self.n_max is not None and value > self.n_max:
            return False
        else:
            return True

    def __repr__(self):
        return 'numeric range: %s to %s' % (self.n_min, self.n_max)


class _FileFormat(_Restriction):
    """Class for file format restrictions. Stores valid file formats, checks filenames against them
    and outputs CTD supported_formats attribute strings.
    """
    def __init__(self, formats):
        super(_FileFormat, self).__init__()
        if isinstance(formats, str):  # to handle ['txt', 'csv', 'tsv'] and '*.txt,*.csv,*.tsv'
            formats = map(lambda x: x.replace('*.', '').strip(), formats.split(','))
        self.formats = formats

    def ctd_restriction_string(self):
        return ','.join(('*.' + f for f in self.formats))

    def _single_check(self, value):
        for f in self.formats:
            if value.endswith('.' + f):
                return True
        return False

    def __repr__(self):
        return 'file formats: %s' % (', '.join(self.formats))


class _Choices(_Restriction):
    """Class for controlled vocabulary restrictions. Stores controlled vocabulary elements, checks
    values against them and outputs CTD restrictions attribute strings.
    """
    def __init__(self, choices):
        super(_Choices, self).__init__()
        if isinstance(choices, str):  # If it actually has to run, a user is screwing around...
            choices = choices.replace(', ', ',').split(',')
        self.choices = choices

    def _single_check(self, value):
        return value in self.choices

    def ctd_restriction_string(self):
        return ','.join(self.choices)

    def __repr__(self):
        return 'choices: %s' % (', '.join(map(str, self.choices)))


class Parameter(object):

    def __init__(self, name, parent, **kwargs):
        """Required positional arguments: `name` string and `parent` ParameterGroup object

        Optional keyword arguments:
            `type`: Python type object, or a string of a valid CTD types.
                    For all valid values, see: CTDopts.CTDTYPE_TO_TYPE.keys()
            `default`: default value. Will be casted to the above type (default None)
            `is_list`: bool, indicating whether this is a list parameter (default False)
            `required`: bool, indicating whether this is a required parameter (default False)
            `description`: string containing parameter description (default None)
            `tags`: list of strings or comma separated string (default [])
            `num_range`: (min, max) tuple. None in either position makes it unlimited
            `choices`: list of allowed values (controlled vocabulary)
            `file_formats`: list of allowed file extensions
        """
        self.name = name
        self.parent = parent

        try:
            self.type = CTDTYPE_TO_TYPE[kwargs.get('type', str)]
        except:
            raise UnsupportedTypeError(kwargs.get('type'))

        self.tags = kwargs.get('tags', [])
        if isinstance(self.tags, str):  # so that tags can be passed as ['tag1', 'tag2'] or 'tag1,tag2'
            self.tags = filter(bool, self.tags.split(','))  # so an empty string doesn't produce ['']
        self.required = CAST_BOOLEAN(kwargs.get('required', False))
        self.is_list = CAST_BOOLEAN(kwargs.get('is_list', False))
        self.description = kwargs.get('description', None)
        self.advanced = CAST_BOOLEAN(kwargs.get('advanced', False))

        default = kwargs.get('default', None)

        self._validate_numerical_defaults(default)
                    
        # TODO 1_6_3: right now the CTD schema requires the 'value' attribute to be present for every parameter.
        # So every time we build a model from a CTD file, we find at least a default='' or default=[]
        # for every parameter. This should change soon, but for the time being, we have to get around this
        # and disregard such default attributes. The below two lines will be deleted after fixing 1_6_3.
        if default == '' or (self.is_list and default == []):
            default = None

        # enforce that default is the correct type if exists. Elementwise for lists
        self.default = None if default is None else map(self.type, default) if self.is_list else self.type(default)
        # same for choices. I'm starting to think it's really unpythonic and we should trust input. TODO

        if self.type == bool:
            assert self.is_list is False, "Boolean flag can't be a list type"
            self.required = False  # override whatever we found. Boolean flags can't be required...
            self.default = False  # ...as they have a False default.

        # Default value should exist IFF argument is not required.
        # TODO: if we can have optional list arguments they don't have to have a default? (empty list)
        # TODO: CTD Params 1.6.3 have a required value attrib. That's very wrong for parameters that are required.
        # ... until that's ironed out, we have to comment this part out.
        #
        # ACTUALLY now that I think of it, letting required fields have value attribs set too
        # can be useful for users who want to abuse CTD and build models from argument-storing CTDs.
        # I know some users will do this (who are not native CTD users just want to convert their stuff
        # with minimal effort) so we might as well let them.
        #
        # if self.required:
        #     assert self.default is None, ('Required field `%s` has default value' % self.name)
        # else:
        #     assert self.default is not None, ('Optional field `%s` has no default value' % self.name)

        self.restrictions = None
        if 'num_range' in kwargs:
            try:
                self.restrictions = _NumericRange(self.type, *kwargs['num_range'])
            except ValueError:
                num_range = kwargs['num_range']
                raise ModelParsingError("Provided range [%s, %s] is not of type %s" %
                                        (num_range[0], num_range[1], self.type))
        elif 'choices' in kwargs:
            self.restrictions = _Choices(map(self.type, kwargs['choices']))
        elif 'file_formats' in kwargs:
            self.restrictions = _FileFormat(kwargs['file_formats'])

    # perform some basic validation on the provided default values...
    # an empty string IS NOT a float/int!        
    def _validate_numerical_defaults(self, default):
        if default is not None:
            if self.type is int or self.type is float: 
                defaults_to_validate = []
                errors_so_far = []
                if self.is_list:
                    # for lists, validate each provided element
                    defaults_to_validate.extend(default)
                else:
                    defaults_to_validate.append(default)
                for default_to_validate in defaults_to_validate:
                    try:
                        if self.type is int:
                            int(default_to_validate)
                        else:
                            float(default_to_validate)
                    except ValueError:
                        errors_so_far.append(default_to_validate)

                if len(errors_so_far) > 0:
                    raise ModelParsingError("Invalid default value(s) provided for parameter %(name)s of type %(type)s:"
                                            " '%(default)s'"
                                            % {"name": self.name,
                                               "type": self.type,
                                               "default": ', '.join(map(str, errors_so_far))})

    def get_lineage(self, name_only=False):
        """Returns a list of zero or more ParameterGroup objects plus this Parameter object at the end,
        ie. the nesting lineage of the Parameter object. With `name_only` setting on, it only returns
        the names of said objects. For top level parameters, it's a list with a single element.
        """
        lineage = []
        i = self
        while i.parent is not None:
            lineage.append(i.name if name_only else i)
            i = i.parent
        lineage.reverse()
        return lineage

    def __repr__(self):
        info = []
        info.append('PARAMETER %s%s' % (self.name, ' (required)' if self.required else ''))
        info.append('  type: %s%s%s' % ('list of ' if self.is_list else '', TYPE_TO_CTDTYPE[self.type],
                                        's' if self.is_list else ''))
        if self.default:
            info.append('  default: %s' % self.default)
        if self.tags:
            info.append('  tags: %s' % ', '.join(self.tags))
        if self.restrictions:
            info.append('  restrictions on %s' % self.restrictions)
        if self.description:
            info.append('  description: %s' % self.description)
        return '\n'.join(info)

    def _xml_node(self, arg_dict=None):
        if arg_dict is not None:  # if we call this function with an argument dict, get value from there
            try:
                value = get_nested_key(arg_dict, self.get_lineage(name_only=True))
            except KeyError:
                value = self.default
        else:  # otherwise take the parameter default
            value = self.default

        # XML attributes to be created (depending on whether they are needed or not):
        # name, value, type, description, tags, restrictions, supported_formats

        attribs = OrderedDict()  # LXML keeps the order, ElemenTree doesn't. We use ElementTree though.
        attribs['name'] = self.name
        if not self.is_list:  # we'll deal with list parameters later, now only normal:
            # TODO: once Param_1_6_3.xsd gets fixed, we won't have to set an empty value='' attrib.
            # but right now value is a required attribute.
            attribs['value'] = '' if value is None else str(value)
            if self.type is bool:  # for booleans str(True) returns 'True' but the XS standard is lowercase
                attribs['value'] = 'true' if value else 'false'
        attribs['type'] = TYPE_TO_CTDTYPE[self.type]
        if self.description:
            attribs['description'] = self.description
        if self.tags:
            attribs['tags'] = ','.join(self.tags)

        # Choices and NumericRange restrictions go in the 'restrictions' attrib, FileFormat has
        # its own attribute 'supported_formats' for whatever historic reason.
        if isinstance(self.restrictions, _Choices) or isinstance(self.restrictions, _NumericRange):
            attribs['restrictions'] = self.restrictions.ctd_restriction_string()
        elif isinstance(self.restrictions, _FileFormat):
            attribs['supported_formats'] = self.restrictions.ctd_restriction_string()

        if self.is_list:  # and now list parameters
            top = Element('ITEMLIST', attribs)
            if value is not None:
                for d in value:
                    SubElement(top, 'LISTITEM', {'value': str(d)})
            return top
        else:
            return Element('ITEM', attribs)


class ParameterGroup(object):
    def __init__(self, name, parent, description=None):
        self.name = name
        self.parent = parent
        self.description = description
        self.parameters = OrderedDict()

    def add(self, name, **kwargs):
        """Registers a parameter in a ParameterGroup. Required: `name` string.

        Optional keyword arguments:
            `type`: Python type object, or a string of a valid CTD types.
                    For all valid values, see: CTDopts.CTDTYPE_TO_TYPE.keys()
            `default`: default value. Will be casted to the above type (default None)
            `is_list`: bool, indicating whether this is a list parameter (default False)
            `required`: bool, indicating whether this is a required parameter (default False)
            `description`: string containing parameter description (default None)
            `tags`: list of strings or comma separated string (default [])
            `num_range`: (min, max) tuple. None in either position makes it unlimited
            `choices`: list of allowed values (controlled vocabulary)
            `file_formats`: list of allowed file extensions
        """
        # TODO assertion if name already exists? It just overrides now, but I'm not sure if allowing this behavior is OK
        self.parameters[name] = Parameter(name, self, **kwargs)
        return self.parameters[name]

    def add_group(self, name, description=None):
        """Registers a child parameter group under a ParameterGroup. Required: `name` string. Optional: `description`
        """
        # TODO assertion if name already exists? It just overrides now, but I'm not sure if allowing this behavior is OK
        self.parameters[name] = ParameterGroup(name, self, description)
        return self.parameters[name]

    def _get_children(self):
        children = []
        for child in self.parameters.itervalues():
            if isinstance(child, Parameter):
                children.append(child)
            elif isinstance(child, ParameterGroup):
                children.extend(child._get_children())
        return children

    def _xml_node(self, arg_dict=None):
        xml_attribs = {'name': self.name}
        if self.description:
            xml_attribs['description'] = self.description

        top = Element('NODE', xml_attribs)
        # TODO: if a Parameter comes after an ParameterGroup, the CTD won't validate. BTW, that should be changed.
        # Of course this should never happen if the argument tree is built properly but it would be
        # nice to take care of it if a user happens to randomly define his arguments and groups.
        # So first we could sort self.parameters (Items first, Groups after them).
        for arg in self.parameters.itervalues():
            top.append(arg._xml_node(arg_dict))
        return top

    def __repr__(self):
        info = []
        info.append('PARAMETER GROUP %s (' % self.name)
        for subparam in self.parameters.itervalues():
            info.append(subparam.__repr__())
        info.append(')')
        return '\n'.join(info)


class CTDModel(object):
    def __init__(self, name=None, version=None, from_file=None, **kwargs):
        """The parameter model of a tool.

        `name`: name of the tool
        `version`: version of the tool
        `from_file`: create the model from a CTD file at provided path

        Other (self-explanatory) keyword arguments:
        `docurl`, `description`, `manual`, `executableName`, `executablePath`, `category`
        """
        if from_file is not None:
            self._load_from_file(from_file)
        else:
            self.name = name
            self.version = version
            # TODO: check whether optional attributes in kwargs are all allowed or just ignore the rest?
            self.opt_attribs = kwargs  # description, manual, docurl, category (+executable stuff).
            self.parameters = ParameterGroup('1', None, 'Parameters of %s' % self.name)  # openMS legacy, top group named "1"

    def _load_from_file(self, filename):
        """Builds a CTDModel from a CTD XML file.
        """
        root = parse(filename).getroot()
        assert root.tag == 'tool', "Invalid CTD file, root is not <tool>"  # TODO: own exception

        self.opt_attribs = {}

        for tool_required_attrib in ['name', 'version']:
            assert tool_required_attrib in root.attrib, "CTD tool is missing a %s attribute" % tool_required_attrib
            setattr(self, tool_required_attrib, root.attrib[tool_required_attrib])

        for tool_opt_attrib in ['docurl', 'category']:
            if tool_opt_attrib in root.attrib:
                self.opt_attribs[tool_opt_attrib] = root.attrib[tool_opt_attrib]

        for tool_element in root:
            if tool_element.tag in ['manual', 'description', 'executableName', 'executablePath']:
                                    # ignoring: cli, logs, relocators. cli and relocators might be useful later.
                self.opt_attribs[tool_element.tag] = tool_element.text
            if tool_element.tag == 'PARAMETERS':
                # tool_element.attrib['version'] == '1.6.2'  # check whether the schema matches the one CTDOpts uses?
                params_container_node = tool_element.find('NODE')
                # we have to check the case in which the parent node contains 
                # item/itemlist elements AND node element children
                params_container_node_contains_items = params_container_node.find('ITEM') is not None or params_container_node.find('ITEMLIST')                 
                # assert params_container_node.attrib['name'] == self.name
                # check params_container_node's first ITEM child's tool version information again? (OpenMS legacy?)
                params = params_container_node.find('NODE')  # OpenMS legacy again, NODE with name="1" on top
                # check for the case when we have PARAMETERS/NODE/ITEM
                if params is None or params_container_node_contains_items:                    
                    self.parameters = self._build_param_model(params_container_node, base=None)
                else:
                    # OpenMS legacy again, PARAMETERS/NODE/NODE/ITEM
                    self.parameters = self._build_param_model(params, base=None)

    def _build_param_model(self, element, base):
        if element.tag == 'NODE':
            if base is None:  # top level group (<NODE name="1">) has to be created on its own
                current_group = ParameterGroup(element.attrib['name'], base, element.attrib.get('description', ''))
            else:  # other groups can be registered as a subgroup, as they'll always have parent base nodes
                current_group = base.add_group(element.attrib['name'], element.attrib.get('description', ''))
            for child in element:
                self._build_param_model(child, current_group)
            return current_group
        elif element.tag == 'ITEM':
            setup = _translate_ctd_to_param(dict(element.attrib))
            base.add(**setup)  # register parameter in model
        elif element.tag == 'ITEMLIST':
            setup = _translate_ctd_to_param(dict(element.attrib))
            setup['default'] = [listitem.attrib['value'] for listitem in element]
            setup['is_list'] = True
            base.add(**setup)  # register list parameter in model

    def add(self, name, **kwargs):
        """Registers a top level parameter to the model. Required: `name` string.

        Optional keyword arguments:
            `type`: Python type object, or a string of a valid CTD types.
                    For all valid values, see: CTDopts.CTDTYPE_TO_TYPE.keys()
            `default`: default value. Will be casted to the above type (default None)
            `is_list`: bool, indicating whether this is a list parameter (default False)
            `required`: bool, indicating whether this is a required parameter (default False)
            `description`: string containing parameter description (default None)
            `tags`: list of strings or comma separated string (default [])
            `num_range`: (min, max) tuple. None in either position makes it unlimited
            `choices`: list of allowed values (controlled vocabulary)
            `file_formats`: list of allowed file extensions
        """
        return self.parameters.add(name, **kwargs)

    def add_group(self, name, description=None):
        """Registers a top level parameter group to the model. Required: `name` string. Optional: `description`
        """
        return self.parameters.add_group(name, description)

    def list_parameters(self):
        """Returns a list of all Parameter objects registered in the model.
        """
        # root node will list all its children (recursively, if they are nested in ParameterGroups)
        return self.parameters._get_children()

    def get_defaults(self):
        """Returns a nested dictionary with all parameters of the model having default values.
        """
        params_w_default = (p for p in self.list_parameters() if p.default is not None)
        defaults = {}
        for param in params_w_default:
            set_nested_key(defaults, param.get_lineage(name_only=True), param.default)
        return defaults

    def validate_args(self, args_dict, enforce_required=0, enforce_type=0, enforce_restrictions=0):
        """Validates an argument dictionary against the model, and returns a type-casted argument
        dictionary with defaults for missing arguments. Valid values for `enforce_required`,
        `enforce_type` and `enforce_restrictions` are 0, 1 and 2, where the different levels are:
            * 0: doesn't enforce anything,
            * 1: raises a warning
            * 2: raises an exception
        """
        # iterate over model parameters, look them up in the argument dictionary, convert to correct type,
        # use default if argument is not present and raise exception if required argument is missing.
        validated_args = {}  # OrderedDict()
        all_params = self.list_parameters()
        for param in all_params:
            lineage = param.get_lineage(name_only=True)
            try:
                arg = get_nested_key(args_dict, lineage)
                # boolean values are the only ones that don't get casted correctly with, say, bool('false')
                typecast = param.type if param.type is not bool else CAST_BOOLEAN
                try:
                    validated_value = map(typecast, arg) if param.is_list else typecast(arg)
                except ValueError:  # type casting failed
                    validated_value = arg  # just keep it as a string (or list of strings)
                    if enforce_type:  # but raise a warning or exception depending on enforcement level
                        if enforce_type == 1:
                            warnings.warn('Argument %s is of wrong type. Expected %s, got: %s' %
                                          (':'.join(lineage), TYPE_TO_CTDTYPE[param.type], arg))
                        else:
                            raise ArgumentTypeError(param, arg)

                if enforce_restrictions and param.restrictions and not param.restrictions.check(validated_value):
                    if enforce_restrictions == 1:
                        warnings.warn('Argument restrictions for %s violated. Restriction: %s. Value: %s' %
                                      (':'.join(lineage), param.restrictions.ctd_restriction_string(), validated_value))
                    else:
                        raise ArgumentRestrictionError(param, validated_value)

                set_nested_key(validated_args, lineage, validated_value)
            except KeyError:  # argument was not found, checking whether required and using defaults if not
                if param.required:
                    if not enforce_required:
                        continue  # this argument will be missing from the dict as required fields have no default value
                    elif enforce_required == 1:
                        warnings.warn('Required argument %s missing' % ':'.join(lineage), UserWarning)
                    else:
                        raise ArgumentMissingError(param)
                else:
                    set_nested_key(validated_args, lineage, param.default)
        return validated_args

    def parse_cl_args(self, cl_args=None, prefix='--', get_remaining=False):
        """Parses command line arguments `cl_args` (either a string or a list like sys.argv[1:])
        assuming that parameter names are prefixed by `prefix` (default '--').

        Returns a nested dictionary with found arguments. Note that parameters have to be registered
        in the model to be parsed and returned.

        Remaining (unmatchable) command line arguments can be accessed if the method is called with
        `get_remaining`. In this case, the method returns a tuple, whose first element is the
        argument dictionary, the second a list of unmatchable command line options.
        """
        cl_parser = argparse.ArgumentParser()
        for param in self.list_parameters():
            lineage = param.get_lineage(name_only=True)
            cl_arg_kws = {}  # argument processing info passed to argparse in keyword arguments, we build them here
            if param.type is bool:  # boolean flags are not followed by a value, only their presence is required
                cl_arg_kws['action'] = 'store_true'
            else:
                # we take every argument as string and cast them only later in validate_args() if
                # explicitly asked for. This is because we don't want to deal with type exceptions
                # at this stage, and prefer the multi-leveled strictness settings in validate_args()
                cl_arg_kws['type'] = str

            if param.is_list:
                # or '+' rather? Should we allow empty lists here? If default is a proper list with elements
                # that we want to clear, this would be the only way to do it so I'm inclined to use '*'
                cl_arg_kws['nargs'] = '*'

            cl_parser.add_argument(prefix + ':'.join(lineage), **cl_arg_kws)  # hardcoded 'group:subgroup:param1'

        cl_arg_list = cl_args.split() if isinstance(cl_args, str) else cl_args
        parsed_args, rest = cl_parser.parse_known_args(cl_arg_list)
        res_args = {}  # OrderedDict()
        for param_name, value in vars(parsed_args).iteritems():
            if value is not None:  # None values are created by argparse if it didn't find the argument, we skip them
                set_nested_key(res_args, param_name.split(':'), value)
        return res_args if not get_remaining else (res_args, rest)

    def generate_ctd_tree(self, arg_dict=None, log=None):
        """Generates an XML ElementTree from the model and returns the top <tool> Element object,
        that can be output to a file (CTDModel.write_ctd() does everything needed if the user
        doesn't need access to the actual element-tree).
        Calling this function without any arguments generates the tool-describing CTD with default
        values. For parameter-storing and logging optional arguments can be passed:

        `arg_dict`: nested dictionary with values to be used instead of defaults.
        `log`: dictionary with the following optional keys:
            'time_start' and 'time_finish': proper XML date strings (eg. datetime.datetime.now(pytz.utc).isoformat())
            'status': exit status
            'output': standard output or whatever output the user intends to log
            'warning': warning logs
            'error': standard error or whatever error log the user wants to store
        """
        tool_attribs = OrderedDict()
        tool_attribs['version'] = self.version
        tool_attribs['name'] = self.name
        tool_attribs['xmlns:xsi'] = "http://www.w3.org/2001/XMLSchema-instance"
        tool_attribs['xsi:schemaLocation'] = "https://github.com/genericworkflownodes/CTDopts/raw/master/schemas/CTD_0_3.xsd"

        opt_attribs = ['docurl', 'category']
        for oo in opt_attribs:
            if oo in self.opt_attribs:
                tool_attribs[oo] = self.opt_attribs[oo]

        tool = Element('tool', tool_attribs)  # CTD root

        opt_elements = ['manual', 'description', 'executableName', 'executablePath']

        for oo in opt_elements:
            if oo in self.opt_attribs:
                SubElement(tool, oo).text = self.opt_attribs[oo]

        if log is not None:
            # log is supposed to be a dictionary, with the following keys (none of them being required):
            # time_start, time_finish, status, output, warning, error
            # generate
            log_node = SubElement(tool, 'log')
            if 'time_start' in log:  # expect proper XML date string like datetime.datetime.now(pytz.utc).isoformat()
                log_node.attrib['executionTimeStart'] = log['time_start']
            if 'time_finish' in log:
                log_node.attrib['executionTimeStop'] = log['time_finish']
            if 'status' in log:
                log_node.attrib['executionStatus'] = log['status']
            if 'output' in log:
                SubElement(log_node, 'executionMessage').text = log['output']
            if 'warning' in log:
                SubElement(log_node, 'executionWarning').text = log['warning']
            if 'error' in log:
                SubElement(log_node, 'executionError').text = log['error']

        # XML.ETREE SYNTAX
        params = SubElement(tool, 'PARAMETERS', {
            'version': '1.6.2',
            'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
            'xsi:noNamespaceSchemaLocation': "https://github.com/genericworkflownodes/CTDopts/raw/master/schemas/Param_1_6_2.xsd"
        })

        # This seems to be some OpenMS hack (defining name, description, version for the second time)
        # but I'll stick to it for consistency
        top_node = SubElement(params, 'NODE', name=self.name, description=self.opt_attribs.get('description', ''))

        SubElement(top_node, 'ITEM',
            name='version',
            value=self.version,
            type='string',
            description='Version of the tool that generated this parameters file.',
            tags='advanced')

        # all the above was boilerplate, now comes the actual parameter tree generation
        args_top_node = self.parameters._xml_node(arg_dict)
        top_node.append(args_top_node)

        # # LXML w/ pretty print syntax
        # return tostring(tool, pretty_print=True, xml_declaration=True, encoding="UTF-8")

        # xml.etree syntax (no pretty print available, so we use xml.dom.minidom stuff)
        return tool

    def write_ctd(self, out_file, arg_dict=None, log=None):
        """Generates a CTD XML from the model and writes it to `out_file`, which is either a string
        to a file path or a stream with a write() method.

        Calling this function without any arguments besides `out_file` generates the tool-describing
        CTD with default values. For parameter-storing and logging optional arguments can be passed:

        `arg_dict`: nested dictionary with values to be used instead of defaults.
        `log`: dictionary with the following optional keys:
            'time_start' and 'time_finish': proper XML date strings (eg. datetime.datetime.now(pytz.utc).isoformat())
            'status': exit status
            'output': standard output or whatever output the user intends to log
            'warning': warning logs
            'error': standard error or whatever error log the user wants to store
        """
        xml_content = parseString(tostring(self.generate_ctd_tree(arg_dict, log), encoding="UTF-8")).toprettyxml()

        if isinstance(out_file, str):  # if out_file is a string, we create and write the file
            with open(out_file, 'w') as f:
                f.write(xml_content)
        else:  # otherwise we assume it's a writable stream and write into that.
            out_file.write(xml_content)


def args_from_file(filename):
    """Takes a CTD file and returns a nested dictionary with all argument values found. It's not
    linked to a model, so there's no type casting or validation done on the arguments. This is useful
    for users who just want to access arguments in CTD files without having to deal with building a CTD model.

    If type casting or validation is required, two things can be done to hack one's way around it:

    Build a model from the same file and call get_defaults() on it. This takes advantage from the
    fact that when building a model from a CTD, the value attributes are used as defaults. Although
    one shouldn't build a model from an argument storing CTD (as opposed to tool describing CTDs)
    there's no technical obstacle to do so.
    """
    def get_args(element, base=None):
        # recursive argument lookup if encountering <NODE>s
        if element.tag == 'NODE':
            current_group = {}  # OrderedDict()
            for child in element:
                get_args(child, current_group)

            if base is not None:
                base[element.attrib['name']] = current_group
            else:
                # top level <NODE name='1'> is the only one called with base=None.
                # As the argument parsing is recursive, whenever the top node finishes, we are done
                # with the parsing and have to return the results.
                return current_group
        elif element.tag == 'ITEM':
            if 'value' in element.attrib:
                base[element.attrib['name']] = element.attrib['value']
        elif element.tag == 'ITEMLIST':
            if element.getchildren():
                base[element.attrib['name']] = [listitem.attrib['value'] for listitem in element]

    root = parse(filename).getroot()
    param_root = root if root.tag == 'PARAMETERS' else root.find('PARAMETERS')
    parameters = param_root.find('NODE').find('NODE')
    return get_args(parameters, base=None)


def parse_cl_directives(cl_args, write_tool_ctd='write_tool_ctd', write_param_ctd='write_param_ctd',
                       input_ctd='input_ctd', prefix='--'):
    '''Parses command line CTD processing directives. `write_tool_ctd`, `write_param_ctd` and `input_ctd`
    string are customizable, and will be parsed for in command line. `prefix` should be one or two dashes,
    default is '--'.

    Returns a dictionary with keys
        'write_tool_ctd': if flag set, either True or the filename provided in command line. Otherwise None.
        'write_param_ctd': if flag set, either True or the filename provided in command line. Otherwise None.
        'input_ctd': filename if found, otherwise None
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument(prefix + write_tool_ctd, nargs='*')
    parser.add_argument(prefix + write_param_ctd, nargs='*')
    parser.add_argument(prefix + input_ctd, type=str)

    cl_arg_list = cl_args.split() if isinstance(cl_args, str) else cl_args  # string or list of args
    directives, rest = parser.parse_known_args(cl_arg_list)
    directives = vars(directives)

    transform = lambda x: None if x is None else True if x == [] else x[0]

    parsed_directives = {}
    parsed_directives['write_tool_ctd'] = transform(directives[write_tool_ctd])
    parsed_directives['write_param_ctd'] = transform(directives[write_param_ctd])
    parsed_directives['input_ctd'] = directives[input_ctd]

    return parsed_directives
