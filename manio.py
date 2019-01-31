import pathlib
import glob
import os
import copy
import collections

import square
import yaml
import k8s_utils

from square import RetVal

# Convenience: global logger instance to avoid repetitive code.
logit = square.logging.getLogger("square")


def parse(file_yaml: dict):
    """Parse all YAML strings in `file_yaml` and return result.

    Inputs:
        file_yaml: Dict[Filename, str]
            Raw data as returned by `load_files`.

    Returns:
        Dict[Filename, Tuple(MetaManifest, dict)]: YAML parsed manifests in
        each file.

    """
    # The output dict will have a list of tuples.
    out = {}

    # Parse the YAML documents from every file.
    for fname, yaml_str in file_yaml.items():
        logit.debug(f"Parsing <{fname}>")

        # Decode the YAML documents in the current file.
        try:
            manifests = list(yaml.safe_load_all(yaml_str))
        except yaml.scanner.ScannerError as err:
            logit.error(
                f"Cannot YAML parse <{fname}>"
                f" - {err.problem} - Line {err.problem_mark.line}"
            )
            return RetVal(None, True)

        # Convert List[manifest] into List[(MetaManifest, manifest)].
        out[fname] = [(square.make_meta(_), _) for _ in manifests]

    # Drop all files without manifests.
    out = {k: v for k, v in out.items() if len(v) > 0}
    num_manifests = [len(_) for _ in out.values()]
    logit.debug(f"Parsed {sum(num_manifests)} in {len(num_manifests)} files")

    # Return the YAML parsed manifests.
    return RetVal(out, False)


def unpack(data: dict):
    """Drop the "Filename" dimension from `data`.

    Returns an error unless all resources are unique. For instance, return an
    error if two files define the same namespace or the same deployment.

    Inputs:
        data: Dict[Filename, Tuple[MetaManifest, dict]]

    Returns:
        Dict[MetaManifest, dict]: flattened version of `data`.

    """
    # Compile a dict that shows which meta manifest was defined in which file.
    # We will use this information short to determine if any resources were
    # specified multiple times in either the same or different file.
    all_meta = collections.defaultdict(list)
    for fname in data:
        for meta, _ in data[fname]:
            all_meta[meta].append(fname)

    # Find out if all meta manifests were unique. If not, log the culprits and
    # return with an error.
    is_unique = True
    for meta, fnames in all_meta.items():
        if len(fnames) > 1:
            is_unique = False
            logit.error(
                f"Meta manifest {meta} was defined {len(fnames)} times: "
                f"{str.join(', ', fnames)}"
            )
    if not is_unique:
        return RetVal(None, True)

    # Compile the input data into a new dict with the meta manifest as key.
    out = {k: v for fname in data for k, v in data[fname]}
    return RetVal(out, False)


def sync(local_manifests, server_manifests):
    """Update the local manifests with the server values and return the result.

    Inputs:
        local_manifests: Dict[Filename, Tuple[MetaManifest, dict]]
        server_manifests: Dict[MetaManifest, dict]

    Returns:
        Dict[Filename, Tuple[MetaManifest, dict]]

    """
    # Create a dict to maps a given MetaManifest to the file which defined it.
    # Do not only store the file but also the index of the YAML manifest inside
    # the file. We will need that information later to find out which manifest
    # in which file we need to update.
    meta_to_fname = {}
    for fname in local_manifests:
        for idx, (meta, _) in enumerate(local_manifests[fname]):
            meta_to_fname[meta] = (fname, idx)
            del meta
        del fname

    # Make a copy of the local manifests to avoid side effects for the caller.
    # We can then safely overwrite the local manifests with the server ones.
    # Furthermore, put it into a default dict because me may have to add
    # manifests to new files.
    out_add_mod = collections.defaultdict(list)
    out_add_mod.update(copy.deepcopy(local_manifests))
    del local_manifests

    # If the meta manifest from the server also exists locally then update the
    # respective manifest, otherwise add it to f"_{namespace}.yaml".
    for meta, manifest in server_manifests.items():
        try:
            # Find out the YAML document index and file that defined `meta`.
            fname, idx = meta_to_fname[meta]
        except KeyError:
            # Put the resource into a "catch-all" file for its namespace. This
            # is necessary because none of the existing YAML files defined that
            # resource.
            out_add_mod[f"_{meta.namespace}.yaml"].append((meta, manifest))
        else:
            # Update the correct YAML document in the correct file.
            out_add_mod[fname][idx] = (meta, manifest)

    # Delete the meta manifests that do not exist on the server. To do just
    # that, iterate over all meta manifests in all files and find out if we
    # have that meta manifest locally anywhere. Only include that manifest in
    # the new output if we do, otherwise skip it to, in effect, delete it.
    out_add_mod_del = {}
    for fname, manifests in out_add_mod.items():
        pruned = [(meta, man) for (meta, man) in manifests if meta in server_manifests]
        out_add_mod_del[fname] = pruned

    return RetVal(out_add_mod_del, False)


def unparse(file_manifests):
    """Convert the Python dict to a Yaml string for each file and return it.

    The output dict can be passed directly to `save_files` to write the files.

    Inputs:
        file_manifests: Dict[Filename:Tuple[MetaManifest, manifest]]
            Typically the output from eg `manio.sync`.

    Returns:
        Dict[Filename:YamlStr]: Yaml representation of all manifests.

    """
    out = {}
    for fname, manifests in file_manifests.items():
        # Verify that this file contains only supported resource kinds.
        kinds = {meta.kind for meta, _ in manifests}
        diff = kinds - set(square.SUPPORTED_KINDS)
        if len(diff) > 0:
            logit.error(f"Found unsupported resource kinds when writing <{fname}>: {diff}")
            return RetVal(None, True)

        # Group the manifests by their "kind", sort each group and compile a
        # new list of grouped and sorted manifests.
        man_sorted = []
        for kind in square.SUPPORTED_KINDS:
            man_sorted += sorted([_ for _ in manifests if _[0].kind == kind])
        assert len(man_sorted) == len(manifests)

        # Drop the MetaManifest, ie
        # Dict[Filename:Tuple[MetaManifest, manifest]] -> Dict[Filename:manifest]
        man_clean = [manifest for _, manifest in man_sorted]

        # Assign the grouped and sorted list of manifests to the output dict.
        out[fname] = man_clean
        del fname, manifests, man_sorted, man_clean

    # Ignore all files whose manifest list is empty.
    out = {k: v for k, v in out.items() if len(v) > 0}

    # Ensure that all dicts are pure Python dicts or there will be problems
    # with the YAML generation below.
    out_clean = {k: k8s_utils.undo_dotdict(v) for k, v in out.items()}

    # Convert all manifest dicts into YAML strings.
    out = {}
    try:
        for fname, v in out_clean.items():
            out[fname] = yaml.safe_dump_all(v, default_flow_style=False)
    except yaml.YAMLError as err:
        logit.error(
            f"YAML error. Cannot create <{fname}>: {err.args[0]} <{str(err.args[1])}>"
        )
        return RetVal(None, True)

    # Return the Dict[Filename:YamlStr]
    return RetVal(out, False)


def save_files(base_path, file_data: dict):
    """Save all `file_data` under `base_path`.

    All paths in `file_data` are relative to `base_path`.

    Inputs:
        base_path: Path
        file_data: Dict[Filename, str]
            The file name (relative to `base_path`) and its content.

    Returns:
        None

    """
    # Python's `pathlib.Path` objects are simply nicer to work with...
    base_path = pathlib.Path(base_path)

    # Iterate over the dict and write each file. Abort on error.
    for fname, yaml_str in file_data.items():
        # Construct absolute file path.
        fname_abs = base_path / fname
        logit.debug(f"Creating path for <{fname}>")

        # Create the necessary parent directories so we can write the file
        # afterwards.
        fname_abs.parent.mkdir(parents=True, exist_ok=True)
        logit.debug(f"Saving YAML file <{fname_abs}>")

        # Write the file. Abort on error.
        try:
            fname_abs.write_text(yaml_str)
        except FileNotFoundError:
            logit.error(f"Could not find <{fname_abs}>")
            return RetVal(None, True)

    # Tell caller that all files were successfully written.
    return RetVal(None, False)


def load_files(base_path, fnames: tuple):
    """Load all `fnames` relative `base_path`.

    The elements of `fname` can have sub-paths, eg `foo/bar/file.txt` is valid
    and would ultimately open f"{base_path}/foo/bar/file.txt".

    Either returns the content of all files or returns with an error and no
    data. It will not return only a sub-set of the files.

    Inputs:
        base_path: Path
        fnames: Iterable[str|Path]
            The file names relative to `base_path`.

    Returns:
        Dict[Filename, str]: the file names (relative to `base_path`) and their
        content as a string.

    """
    # Python's `pathlib.Path` objects are simply nicer to work with...
    base_path = pathlib.Path(base_path)

    # Load each file and store its name and content in the `out` dictionary.
    out = {}
    for fname_rel in fnames:
        # Construct absolute file path.
        fname_abs = base_path / fname_rel
        logit.debug(f"Loading {fname_abs}")

        # Read the file. Abort on error.
        try:
            # The str() is necessary because `fname_rel` may be a `pathlib.Path`.
            out[str(fname_rel)] = fname_abs.read_text()
        except FileNotFoundError:
            logit.error(f"Could not find <{fname_abs}>")
            return RetVal(None, True)

    # Return the read files.
    return RetVal(out, False)


def load(folder):
    """Load all "*.yaml" files under `folder` (recursively).

    Ignores all files not ending in ".yaml".

    Returns no data in the case of an error.

    NOTE: this is merely a wrapper around the various low-level functions to
    load and parse the YAML files.

    Input:
        folder: str|Path
            Source folder.

    Returns:
        Dict[Filename, Tuple(MetaManifest, dict)]: parsed YAML files.

    """
    # Python's `pathlib.Path` objects are simply nicer to work with...
    folder = pathlib.Path(folder)

    # Compile the list of all YAML files in `folder` but only store their path
    # relative to `folder`.
    fnames = [_.relative_to(folder) for _ in folder.rglob("*.yaml")]

    # Load the files and abort on error.
    fdata_raw, err = load_files(folder, fnames)
    if err:
        return RetVal(None, True)

    # Return the YAML parsed manifests.
    return parse(fdata_raw)


def save(folder, manifests: dict):
    """Convert all `manifests` to YAML and save them.

    Returns no data in the case of an error.

    NOTE: this is merely a wrapper around the various low-level functions to
    create YAML string and save the files.

    Input:
        folder: str|Path
            Source folder.
        file_manifests: Dict[Filename, Tuple(MetaManifest, dict)]
            Names of files and their Python dicts to save as YAML.

    Returns:
        None

    """
    # Python's `pathlib.Path` objects are simply nicer to work with...
    folder = pathlib.Path(folder)

    # Convert the manifest to YAML strings. Abort on error.
    fdata_raw, err = unparse(manifests)
    if err:
        return RetVal(None, True)

    # Save the files to disk.
    return save_files(folder, fdata_raw)
