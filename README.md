# CTDopts
`CTDopts` is a module for enabling tools with CTD reading/writing, argument parsing, validating and manipulating capabilities.

Please check out [example.py](example.py) for an overview of CTDopt's features.

## Installing
`CTDopts` is available in the Anaconda Cloud under the `workflowconversion` channel. You can install the latest stable release using `conda` by executing the following command:

```sh
$ conda install --channel workflowconversion ctdopts
```
    
Or, if you want the latest, possibly unstable, version, you can clone the `CTDopts` repository from https://github.com/WorkflowConversion/CTDopts.

## Information for Developers
In order to upload `CTDopts` to the Anaconda Cloud for distribution, you should familiarize yourself with the [Anaconda Cloud documentation on packages](https://docs.continuum.io/anaconda-cloud/user-guide/tasks/work-with-packages). A summary of the required steps to update `CTDopts` on the Anaconda Cloud is presented here:

1. Make sure you've installed the `anaconda-client` and `conda-build` packages using `conda`. This needs to be done once per development environment.
1. Commit your changes to the code locally.
1. Bump up the version. This is a two-fold process:
    1. Update the [meta.yaml file](dist/conda/meta.yaml), in particular the `package.version` and `source.git_rev` properties. Commit your changes locally.
    1. Tag the state of the repository using `git tag vX.Y`.
1. Push all changes to `CTDopts` repository. Remember to tell git to also *push* the newly created tag (i.e., by invoking `git push origin --tags`).
1. Change your working directory to `dist/conda` and execute the following command (you will be asked for credentials to finalize the upload after the build):

```sh
$ conda build .
```

**IMPORTANT:** The `conda` build process **will not** use your local repository, rather, it will use the revision and repository stated in your [meta.yaml file](dist/conda/meta.yaml) under the `source` property. This is why it is important to commit all your changes and to update the version before building/distributing. 
    