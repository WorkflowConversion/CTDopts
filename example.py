# or for easier access of certain commonly used module methods
import datetime
import pprint
import pytz

import CTDopts.CTDopts  # once you installed it, it's just CTDopts
from CTDopts.CTDopts import CTDModel, args_from_file, parse_cl_directives, flatten_dict, override_args, ArgumentRestrictionError


# let's set up a PrettyPrinter so nested dictionaries are easier to follow later
pp = pprint.PrettyPrinter(indent=4)
pretty_print = pp.pprint

# First, we'll set up a CTD model. There are two different ways to do that:
#    1. Define it in Python using CTDopts.CTDModel's methods
#    2. load it from a CTD file

# Every CTD Model has to have at least a name and a version, plus any of the optional attributes below them.
model = CTDModel(
    name='exampleTool',  # required
    version='1.0',  # required
    description='This is an example tool presenting CTDopts usage',
    manual='manual string',
    docurl='http://dummy.url/docurl.html',
    category='testing',
    executableName='exampletool',
    executablePath='/path/to/exec/exampletool-1.0/exampletool'
)

# The parameters of the tool have to be registered the following way:
model.add(
    'positive_int',  # parameter name
    type=int,  # parameter type. For a list of CTD-supported types see CTDopts.CTDTYPE_TO_TYPE.keys()
    num_range=(0, None),  # numeric range restriction: tuple with minimum and maximum values. None means unlimited
    default=5,
    tags=['advanced', 'magic'],  # for certain workflow engines that make use of parameter tags
    description='A positive integer parameter'
)

model.add(
    'input_files',
    required=True,
    type='input-file',  # or 'output-file'
    is_list=True,  # for list parameters with an arbitrary number of values
    file_formats=['fastq', 'fastq.gz'],  # filename restrictions
    description='A list of filenames to feed this dummy tool with'
)

model.add(
    'this_that',
    type=str,
    choices=['this', 'that'],  # controlled vocabulary
    default='this',
    description='A controlled vocabulary parameter. Allowed values `this` or `that`.'
)

# Certain tools may want to group parameters together. One can define them like this:
subparams = model.add_group('subparams', 'Grouped settings')

# register sub-parameters to a group:
subparams.add(
    'param_1',
    type=float,
    default=5.5,
    description='Some floating point setting.'
)

subparams.add(
    'param_2',
    is_list=True,
    type=float,
    tags=['advanced'],
    default=[0.0, 2.5, 5.0],
    description='A list of floating point settings'
)

subsubparams = subparams.add_group('subsubparam', 'A group of sub-subsettings')
subsubparams.add(
    'param_3',
    type=int,
    default=2,
    description="A subsetting's subsetting"
)

# Now we have a CTDModel. To write the model to a CTD (xml) file:
print('Model being written to exampleTool.ctd...\n')
model.write_ctd('exampleTool.ctd')

# However, if we already have a CTD model for a tool, we can spare the pain of defining it like above, we can just
# load it from a file directly. Like this:
print('Model loaded from exampleTool.ctd...\n')
model_2 = CTDModel(from_file='exampleTool.ctd')

# We can list all the model's parameters. The below call will get a list of all Parameter objects registered in the model.
# These objects store name, type, default, restriction, parent group etc. information we set above.
params = model.list_parameters()

print("For debugging purposes we can output a human readable representation of Parameter objects. Here's the first one:")
print(params[0])
print

# Let's print out the name attributes of these parameters.
print('The following parameters were registered in the model:')
print([p.name for p in params])
print

# In the above model, certain parameters were registered under parameter groups. We can access their 'lineage' and see
# their nesting levels. Let's display nesting levels separated by colons:
print('The same parameters with subgroup information, if they were registered under parameter groups:')
print([':'.join(p.get_lineage(name_only=True)) for p in params])
print()
# (Parameter.get_lineage() returns a list of ParameterGroups down to the leaf Parameter. `name_only` setting returns
# only the names of the objects, instead of the actual Parameter objects.

# Some of the parameters had default values in the model. We can get those:
print('A dictionary of parameters with default values, returned by CTDModel.get_defaults():')
defaults = model_2.get_defaults()
pretty_print(defaults)
print()

print('As you can see, parameter values are usually stored in nested dictionaries. If you want a flat dictionary, you can'
      'get that using CTDopts.flatten_dict(). Flat keys can be either tuples of tree node (subgroup) names down to the parameter...')
flat_defaults = flatten_dict(defaults)
pretty_print(flat_defaults)
print()

print('...or they can be strings where nesing levels are separated by colons:')
flat_defaults_colon = flatten_dict(defaults, as_string=True)
pretty_print(flat_defaults_colon)
print()

print('We can create dictionaries of arguments on our own that we want to validate against the model.'
      'CTDopts can read them from argument-storing CTD files or from the command line, but we can just define them in a '
      'nested dictionary on our own as well. We start with defining them explicitly.')
new_values = {
    'positive_int': 111,
    'input_files': ['file1.fastq', 'file2.fastq', 'file3.fastq'],
    'subparams': {'param_1': '999.0'}
}
pretty_print(new_values)
print()

print("We can validate these arguments against the model, and get a dictionary with parameter types correctly casted "
      "and defaults set. Note that subparams:param_1 was casted from string to a floating point number because that's how it "
      "was defined in the model.")
validated = model.validate_args(new_values)
pretty_print(validated)
print()

print('We can write a CTD file containing these validated argument values. Just call CTDModel.write_ctd() with an extra '
      'parameter: the nested argument dictionary containing the actual values.')
model.write_ctd('exampleTool_preset_params.ctd', validated)
print()

print('As mentioned earlier, CTDopts can load argument values from CTD files. Feel free to change some values in '
      "exampleTool_preset_params.ctd you've just written, and load it back.")
args_from_ctd = args_from_file('exampleTool_preset_params.ctd')
pretty_print(args_from_ctd)
print()
print("Notice that all the argument values are strings now. This is because we didn't validate them against the model, "
      "just loaded some stuff from a file into a dictionary. If you want to cast them, call CTDModel.validate_args():")
validated_2 = model.validate_args(args_from_ctd)
pretty_print(validated_2)
print()

print("Now certain parameters may have restrictions that we might want to validate for as well. Let's set the parameter "
      "positive_int to a negative value, and try to validate it with a strictness level enforce_restrictions=1. This "
      "will register a warning, but still accept the value.")
validated_2['positive_int'] = -5
_ = model.validate_args(validated_2, enforce_restrictions=1)
print()

print("Validation enforcement levels can be 0, 1 or 2 for type-casting, restriction-checking and required argument presence. "
      "They can be set with the keywords enforce_type, enforce_restrictions and enforce_required respectively. Let's increase "
      "strictness for restriction checking. CTDModel.validate_args() will now raise an exception that we'll catch:\n")
try:
    model.validate_args(validated_2, enforce_restrictions=2)  # , enforce_type=0, enforce_required=0
except ArgumentRestrictionError as ee:
    # other exceptions: ArgumentTypeError, ArgumentMissingError, all subclasses of Argumenterror
    print(ee)

print()
print("One might want to combine arguments loaded from a CTD file with arguments coming from elsewhere, like the command line."
      "In that case, the method CTDopts.override_args(*arg_dicts) creates a combined argument dictionary where argument values "
      "are always taken from the rightmost (last) dictionary that has them. Let's override a few parameters:")
override = {
    'this_that': 'that',
    'positive_int': 777
}
overridden = override_args(validated, override)
pretty_print(overridden)
print()

print("So how to deal with command line arguments? If we have a model, we can look for its arguments. "
      "Call CTDModel.parse_cl_args() with either a string of the command line call or a list with the split words. "
      "By default, it will assume a '--' prefix before parameter names, but it can be overridden with prefix='-'."
      "Grouped parameters are expected in --group:subgroup:param_x format.")
cl_args = model.parse_cl_args('--positive_int 44 --subparams:param_2 5.0 5.5 6.0 --input_files a.fastq b.fastq')
pretty_print(cl_args)
print()
# # you can get unmatchable command line arguments with get_remaining=True like:
# cl_args, unparsed = model.parse_cl_args('--positive_int 44 --subparams:param_2 5.0 5.5 6.0 --unrelated_stuff abc', get_remaining=True)

print("Override other parameters with them, and validate it against the model:")
overridden_with_cl = override_args(validated, cl_args)
validated_3 = model.validate_args(overridden_with_cl)
pretty_print(validated_3)
print

print("One last thing: certain command line directives that are specific to CTD functionality can be parsed for, "
      "to help your script performing common tasks. These are CTD argument input, CTD model file writing and CTD argument "
      "file writing. CTDopts.parse_cl_directives() can also be customized as to what directives to look for if the defaults "
      "--input_ctd, --write_tool_ctd and --write_param_ctd respectively don't satisfy you.")
directives_1 = parse_cl_directives('--input_ctd exampleTool_preset_params.ctd --write_param_ctd new_preset_params.ctd')
pretty_print(directives_1)
directives_2 = parse_cl_directives('-inctd exampleTool_preset_params_2.ctd -toolctd ', input_ctd='inctd', write_tool_ctd='toolctd', prefix='-')
pretty_print(directives_2)
# the returned dictionary always contains the following three keys:
#   'input_ctd'
#   'write_tool_ctd'
#   'write_param_ctd'
# and their values are either a filename (if it was passed), a boolean True, if the flag was set but no filename provided
# (expecting the tool to use default values, like toolName.ctd) or None if the flag wasn't used at all.

# for example, if directives['input_ctd'] is set, one would load arguments from that file with
# CTDopts.args_from_file(directives['input_ctd']), validate them and run the tool.
# If I found directives['write_tool_ctd'], I'd immediately output the tool's CTD model with
# model.write_ctd(directives['write_tool_ctd']), etc.

print("Finally, writing CTDs with logging information, passing a dictionary"
      "with a 'log' keyword, using any or all of the fields shown below.")
time_start = datetime.datetime.now(pytz.utc).isoformat()
# do stuff
output = 'Output of my program, however I generated or logged it'
errors = 'Standard error output of my program, however I caught or redirected them'
warnings = 'Warnings of my program'
exitstatus = '1'
time_finish = datetime.datetime.now(pytz.utc).isoformat()

log = {
    'time_start': time_start,  # make sure to give it a legal XML date string if you can.
    'time_finish': time_finish,  # You can generate them with datetime.datetime.now(pytz.utc).isoformat()
    'status': exitstatus,
    'output': output,
    'warning': warnings,
    'error': errors
}

model.write_ctd('exampleTool_w_logging.ctd', validated_3, log)


# Methods you might find helpful to deal with argument dictionaries (see docstrings):
# CTDopts.set_nested_key(dictionary, tuple_w_levels, value) and
# CTDopts.get_nested_key(dictionary, tuple_w_levels for nested dictionaries
