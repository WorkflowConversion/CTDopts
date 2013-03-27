from pyCTD import pyCTD

param_definitions = pyCTD(
    name='testTool',
    version='0.0.1',
    description='This is a dummy test tool presenting pyCTD usage',
    manual='manual',
    docurl='http://dummy.url/docurl.html',
    category='testing'
    )

main_params = param_definitions.get_root()

main_params.add(
    'positive_number',
    type=int,
    num_range=(0, None),
    default=5,
    description='A positive integer parameter'
    )

main_params.add(
    'input_files',
    is_list=True,
    required=True,
    type=str,
    file_formats=['fastq', 'fastq.gz'],
    tags=['input file', 'required'],
    description='A list of filenames you want to feed this dummy program with'
    )

main_params.add(
    'this_or_that',
    type=str,
    choices=['this', 'that'],
    default='this',
    tags=['advanced'],
    description='A controlled vocabulary parameter. Allowed values: `this` or `that`'
    )

subparams = main_params.add_group('subparams', 'Further minor settings of some algorithm')

subparams.add(
    'param_1',
    type=float,
    tags=['advanced'],
    default=5.5,
    description='Some minor floating point setting'
    )

subparams.add(
    'param_2',
    is_list=True,
    type=float,
    tags=['advanced'],
    default=[0.0, 2.5, 5.0],
    description='A list of floating point settings for, say, multiple runs of analysis'
    )

minorparams = subparams.add_group('subsubsetting', 'A group of sub-subsettings')
minorparams.add(
    'param_3',
    type=int,
    tags=['advanced'],
    default=2,
    description="A subsetting's subsetting"
    )

# Tool parameter definition is over. Let's use it now.
#
# It could have been called with either:
#   -write_ctd: we write testTool.ctd in the current directory and exit
#   -load_ini some_settings.ini: we import arguments from an INI file and start working with our tool
#   normal command line arguments: we parse those and start working

args = param_definitions.parse_args()

print 'Arguments successfully loaded and verified against restrictions. We can start working with:\n', args

# accessing stuff just like argparse.
print 'Positive number parameter: ', args.positive_number

# or dictionary interface like arg_dict['positive_number'] or arg_dict['subparams:param_1']
# subparameters can only be accessed like that anyway as colons can't be used in python identifiers
arg_dict = vars(args)
print 'Subparameter 1: ', arg_dict['subparams:param_1']


# try running it with invalid parameters like -positive_number -10 or -input_files xxx.wrongextension etc.

parsed = param_definitions.parse_args('-positive_number -10 -input_files xxx.fastq yyy.fastq.gz -subparams:param_2 1.2 3.4 5.6'.split())
