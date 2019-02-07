"""Define the structure of the stripped manifest schema.

A stripped manifest is a sub-set of a normal manifest. The remaining keys
capture the salient information about the resource.

For instance, almost all manifest can have a "status" field. Albeit useful for
diagnostics, it makes no sense to compute diffs of "status" fields and submit
them in patches.

# Schema Conventions
Schemas are normal dictionaries without a depth limit.  All keys correspond to
a K8s manifest key. All value must be either dicts themselves, a bool to
specify whether the fields must be included in the stripped manifest, or None
if the field is not mandatory but should be included.

* True: field will be included. It is an error if the input manifest lacks it.
* False: field will not be included. It is an error if the input manifest has it.
* None: field will be included if the input manifest has it, and ignored otherwise.

"""
schema_1_9 = {
    "Deployment": {
        "metadata": {
            "labels": None,
            "name": True,
            "namespace": True,
        },
        "spec": True,
    },
    "Namespace": {
        "metadata": {
            "labels": None,
            "name": True,
            "namespace": False
        },
        "spec": True,
    },
    "Service": {
        "metadata": {
            "labels": None,
            "name": True,
            "namespace": True,
        },
        "spec": True,
    },
}


RESOURCE_SCHEMA = {
    "1.9": schema_1_9,
    "1.10": schema_1_9,
}