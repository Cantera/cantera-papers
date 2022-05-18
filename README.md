# Cantera Papers

This repository hosts the code for the Cantera `papers` application.

`papers` ingests DOIs of user-submitted papers where they used Cantera and produces a nicely formatted page listing each paper.

## Dependency Management

We use `conda-lock` for dependency management. To update a dependency, edit `environment.yml` for dependencies of the main application, or `dev-environment.yml` for dependencies required to develop the application. After updating one of the files, run:

```shell
conda-lock lock -f environment.yml -f dev-environment.yml --mamba
```

This updates the `conda-lock.yml` file. Then run:

```shell
conda-lock install --name <your-environment-name> --mamba
```
