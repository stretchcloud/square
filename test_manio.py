import random

import yaml
import manio
import square
import test_square

import unittest.mock as mock
from square import RetVal


def mk_deploy(name: str, ns: str="namespace"):
    return test_square.make_manifest("Deployment", ns, name)


class TestYamlManifestIO:
    @classmethod
    def setup_class(cls):
        square.setup_logging(9)

    def yamlfy(self, data):
        return {
            k: yaml.safe_dump_all(v, default_flow_style=False)
            for k, v in data.items()
        }

    def test_parse_ok(self):
        """Test function must be able to parse the Yaml string and compile a dict."""
        # Construct manifests in the way as `load_files` returns them.
        dply = [mk_deploy(f"d_{_}") for _ in range(10)]
        meta = [square.make_meta(_) for _ in dply]
        fdata_test_in = {
            "m0.yaml": [dply[0], dply[1]],
            "m2.yaml": [dply[2]],
            "m3.yaml": [],
        }
        fdata_test_in = self.yamlfy(fdata_test_in)

        # We expect a dict with the same keys as the input. The dict values
        # must be a list of tuples, each of which contains the MetaManifest and
        # actual manifest as a Python dict.
        expected = {
            "m0.yaml": [(meta[0], dply[0]), (meta[1], dply[1])],
            "m2.yaml": [(meta[2], dply[2])],
        }
        assert manio.parse(fdata_test_in) == RetVal(expected, False)

    def test_parse_err(self):
        """Intercept YAML decoding errors."""
        # Construct manifests in the way as `load_files` returns them.
        fdata_test_in = {"m0.yaml": "invalid :: - yaml"}
        assert manio.parse(fdata_test_in) == RetVal(None, True)

    def test_unpack_ok(self):
        """Test function must remove the filename dimension.

        All meta manifests are unique in this test. See `test_unpakc_err` for
        what happens if not.

        """
        src = {
            "file0.txt": [("meta0", "manifest0"), ("meta1", "manifest1")],
            "file1.txt": [("meta2", "manifest2")],
        }
        ret, err = manio.unpack(src)
        assert err is False
        assert ret == {
            "meta0": "manifest0",
            "meta1": "manifest1",
            "meta2": "manifest2",
        }

    def test_unpack_err(self):
        """The MetaManifests must be unique across all source files."""

        # Two resources with same meta information in same file.
        src = {
            "file0.txt": [("meta0", "manifest0"), ("meta0", "manifest0")],
        }
        assert manio.unpack(src) == RetVal(None, True)

        # Two resources with same meta information in different files.
        src = {
            "file0.txt": [("meta0", "manifest0")],
            "file1.txt": [("meta0", "manifest0")],
        }
        assert manio.unpack(src) == RetVal(None, True)

    def test_sync_modify_delete_ok(self):
        """Add, modify and delete a few manifests.

        Create fake inputs for the test function, namely local- and remote
        manifests. Their structure is slightly different in that the local
        manifests still carry the file name in their data structure whereas the
        server ones do not.

        """
        # First, create the local manifests as `load_files` would return it.
        dply_1 = [mk_deploy(f"d_{_}", "ns1") for _ in range(10)]
        meta_1 = [square.make_meta(_) for _ in dply_1]
        dply_2 = [mk_deploy(f"d_{_}", "ns2") for _ in range(10)]
        meta_2 = [square.make_meta(_) for _ in dply_2]
        loc_man = {
            "m0.yaml": [(meta_1[0], "0"), (meta_1[1], "1"), (meta_2[2], "2")],
            "m1.yaml": [(meta_2[3], "3"), (meta_1[4], "4")],
            "m2.yaml": [(meta_1[5], "5")],
        }

        # Create server manifests as `download_manifests` would return it. Only
        # the MetaManifests (ie dict keys) are relevant whereas the dict values
        # are not but serve to improve code readability here.
        srv_man = {
            meta_1[0]: "0",         # same
            meta_1[1]: "modified",  # modified
            meta_2[2]: "2",         # same
                                    # delete [3]
            meta_1[4]: "4",         # same
                                    # delete [5]
            meta_1[6]: "new",       # new
            meta_2[7]: "new",       # new
            meta_1[8]: "new",       # new
        }

        # The expected outcome is that the local manifests were updated,
        # either overwritten (modified), deleted or put into a default
        # manifest.
        expected = {
            "m0.yaml": [(meta_1[0], "0"), (meta_1[1], "modified"), (meta_2[2], "2")],
            "m1.yaml": [(meta_1[4], "4")],
            "m2.yaml": [],
            "_ns1.yaml": [(meta_1[6], "new"), (meta_1[8], "new")],
            "_ns2.yaml": [(meta_2[7], "new")],
        }
        assert manio.sync(loc_man, srv_man) == RetVal(expected, False)

    def test_sync_catch_all_files(self):
        """Verify that syncing the catch-all files works as expected.

        This requires a special test to ensure these auto generated catch-all
        files behave like their "normal" user created counterparts.

        """
        # First, create the local manifests as `load_files` would return it.
        dply_1 = [mk_deploy(f"d_{_}", "ns1") for _ in range(20)]
        meta_1 = [square.make_meta(_) for _ in dply_1]
        dply_2 = [mk_deploy(f"d_{_}", "ns2") for _ in range(20)]
        meta_2 = [square.make_meta(_) for _ in dply_2]
        loc_man = {
            "_ns1.yaml": [
                (meta_1[1], "1"), (meta_1[2], "2"), (meta_1[3], "3"), (meta_1[5], "5")
            ],
            "_ns2.yaml": [
                (meta_2[2], "2"), (meta_2[6], "6"),
            ]
        }

        # Create server manifests as `download_manifests` would return it. Only
        # the MetaManifests (ie dict keys) are relevant whereas the dict values
        # are not but serve to improve code readability here.
        srv_man = {
            # --- _ns1.yaml ---
            meta_1[0]: "0",         # new
            meta_1[1]: "modified",  # modified
            meta_1[2]: "2",         # same
                                    # delete [3]
                                    # [4] never existed
                                    # delete [5]

            # --- _ns2.yaml ---
            meta_2[0]: "0",         # new
            meta_2[9]: "9",         # new
            meta_2[7]: "7",         # new
            meta_2[6]: "modified",  # modified
                                    # delete [2]
            meta_2[5]: "5",         # new
            meta_2[3]: "3",         # new
        }

        # The expected outcome is that the local manifests were updated,
        # either overwritten (modified), deleted or put into a default
        # manifest.
        # NOTE: this test _assumes_ that the `srv_man` dict iterates over its
        # keys in insertion order, which is guaranteed for Python 3.7.
        expected = {
            "_ns1.yaml": [
                (meta_1[1], "modified"), (meta_1[2], "2"), (meta_1[0], "0"),
            ],
            "_ns2.yaml": [
                (meta_2[6], "modified"), (meta_2[0], "0"), (meta_2[9], "9"),
                (meta_2[7], "7"), (meta_2[5], "5"), (meta_2[3], "3"),
            ]
        }
        assert manio.sync(loc_man, srv_man) == RetVal(expected, False)

    def test_sync_new_namespaces(self):
        """Create catch-all files for new namespaces.

        This tests verifies that namespace resources end up in the correct
        catch-all files. This is a corner case because the correct catch-all
        file for namespaces is based on the `name` attributed of that
        namespace's `MetaManifest`, not the `namespace` attribute which is None
        for namespaces.

        """
        # Convenience to improve readability.
        def mm(*args):
            return square.make_meta(test_square.make_manifest(*args))

        meta_ns_a = mm("Namespace", None, "a")
        meta_ns_b = mm("Namespace", None, "b")
        meta_svc_a = [mm("Service", "a", f"s{_}") for _ in range(10)]
        meta_dply_a = [mm("Deployment", "a", f"d{_}") for _ in range(10)]
        meta_svc_b = [mm("Service", "b", f"s{_}") for _ in range(10)]
        meta_dply_b = [mm("Deployment", "b", f"d{_}") for _ in range(10)]

        # For this test we can pretend that we do not have any local manifest
        # files yet.
        loc_man = {}

        # Create server manifests as `download_manifests` would return it. Only
        # the MetaManifests (ie dict keys) are relevant whereas the dict values
        # are not but serve to improve code readability here.
        srv_man = {
            # --- _a.yaml ---
            meta_ns_a: "ns_a",
            meta_svc_a[0]: "svc_a_0",
            meta_svc_a[1]: "svc_a_1",
            meta_dply_a[3]: "dply_a_3",
            meta_dply_a[4]: "dply_a_4",

            # --- _b.yaml ---
            meta_ns_b: "ns_b",
            meta_svc_b[0]: "svc_b_0",
            meta_svc_b[1]: "svc_b_1",
            meta_dply_b[3]: "dply_b_3",
            meta_dply_b[4]: "dply_b_4",
        }

        # The expected outcome is that the local manifests were updated,
        # either overwritten (modified), deleted or put into a default
        # manifest.
        # NOTE: this test _assumes_ that the `srv_man` dict iterates over its
        # keys in insertion order, which is guaranteed for Python 3.7.
        expected = {
            "_a.yaml": [
                (meta_ns_a, "ns_a"),
                (meta_svc_a[0], "svc_a_0"),
                (meta_svc_a[1], "svc_a_1"),
                (meta_dply_a[3], "dply_a_3"),
                (meta_dply_a[4], "dply_a_4"),
            ],
            "_b.yaml": [
                (meta_ns_b, "ns_b"),
                (meta_svc_b[0], "svc_b_0"),
                (meta_svc_b[1], "svc_b_1"),
                (meta_dply_b[3], "dply_b_3"),
                (meta_dply_b[4], "dply_b_4"),
            ],
        }
        assert manio.sync(loc_man, srv_man) == RetVal(expected, False)

    def test_unparse_ok(self):
        """Basic use case: convert Python dicts to YAML strings."""
        # Create valid MetaManifests.
        meta = [square.make_meta(mk_deploy(f"d_{_}")) for _ in range(10)]

        # Input to test function and expected output.
        file_manifests = {
            "m0.yaml": [(meta[0], "0"), (meta[1], "1")],
            "m1.yaml": [(meta[2], "2")],
        }
        expected = self.yamlfy({
            "m0.yaml": ["0", "1"],
            "m1.yaml": ["2"],
        })

        # Run the tests.
        assert manio.unparse(file_manifests) == RetVal(expected, False)

    def test_unparse_sorted_ok(self):
        """The manifests in each file must be grouped and sorted.

        Every YAML file we create must group all resource types in this order:
        namespaces, services, deployment.

        All resources must be sorted by name inside each group.

        """
        def mm(*args):
            return square.make_meta(test_square.make_manifest(*args))

        # Create valid MetaManifests.
        meta_ns_a = mm("Namespace", "a", None)
        meta_ns_b = mm("Namespace", "b", None)
        meta_svc_a = [mm("Service", "a", f"d_{_}") for _ in range(10)]
        meta_dply_a = [mm("Deployment", "a", f"d_{_}") for _ in range(10)]
        meta_svc_b = [mm("Service", "b", f"d_{_}") for _ in range(10)]
        meta_dply_b = [mm("Deployment", "b", f"d_{_}") for _ in range(10)]

        # Define manifests in the correctly grouped and sorted order for three
        # YAML files.
        sorted_manifests_1 = [
            (meta_ns_a, "ns_a"),
            (meta_ns_b, "ns_b"),
            (meta_svc_a[0], "svc_a_0"),
            (meta_svc_a[1], "svc_a_1"),
            (meta_svc_b[0], "svc_b_0"),
            (meta_svc_b[1], "svc_b_1"),
            (meta_dply_a[0], "dply_a_0"),
            (meta_dply_a[1], "dply_a_1"),
            (meta_dply_b[0], "dply_b_0"),
            (meta_dply_b[1], "dply_b_1"),
        ]
        sorted_manifests_2 = [
            (meta_svc_a[0], "svc_a_0"),
            (meta_svc_a[1], "svc_a_1"),
            (meta_dply_b[0], "dply_b_0"),
            (meta_dply_b[1], "dply_b_1"),
        ]
        sorted_manifests_3 = [
            (meta_ns_a, "ns_a"),
            (meta_svc_b[0], "svc_b_0"),
            (meta_dply_a[1], "dply_a_1"),
        ]

        # Compile input and expected output for test function.
        file_manifests = {
            "m0.yaml": sorted_manifests_1.copy(),
            "m1.yaml": sorted_manifests_2.copy(),
            "m2.yaml": sorted_manifests_3.copy(),
        }
        expected = {k: [man for _, man in v] for k, v in file_manifests.items()}
        expected = self.yamlfy(expected)

        # Shuffle the manifests in each file and verify that the test function
        # always produces the correct order, ie NS, SVC, DEPLOY, and all
        # manifests in each group sorted by namespace and name.
        for i in range(10):
            for fname in file_manifests:
                random.shuffle(file_manifests[fname])
            assert manio.unparse(file_manifests) == RetVal(expected, False)

    def test_unparse_invalid_manifest(self):
        """Must handle YAML errors gracefully."""
        # Create valid MetaManifests.
        meta = [square.make_meta(mk_deploy(f"d_{_}")) for _ in range(10)]

        # Input to test function where one "manifest" is garbage that cannot be
        # converted to a YAML string, eg a Python frozenset.
        file_manifests = {
            "m0.yaml": [(meta[0], "0"), (meta[1], frozenset(("invalid", "input")))],
            "m1.yaml": [(meta[2], "2")],
        }

        # Test function must return with an error.
        assert manio.unparse(file_manifests) == RetVal(None, True)

    def test_unparse_unknown_kinds(self):
        """Must handle unknown resource kinds gracefully."""
        invalid_kinds = (
            "deployment",       # wrong capitalisation
            "DEPLOYMENT",       # wrong capitalisation
            "foo",              # unknown
            "Pod",              # we do not support Pod manifests
        )

        # Convenience.
        def mm(*args):
            return square.make_meta(test_square.make_manifest(*args))

        # Test function must gracefully reject all invalid kinds.
        for kind in invalid_kinds:
            file_manifests = {"m0.yaml": [(mm(kind, "ns", "name"), "0")]}
            assert manio.unparse(file_manifests) == RetVal(None, True)

    def test_unparse_known_kinds(self):
        """Must handle all known resource kinds without error."""
        # Convenience.
        def mm(*args):
            return square.make_meta(test_square.make_manifest(*args))

        # Test function must gracefully reject all invalid kinds.
        for kind in square.SUPPORTED_KINDS:
            file_manifests = {"m0.yaml": [(mm(kind, "ns", "name"), "0")]}
            assert manio.unparse(file_manifests).err is False

    def test_manifest_lifecycle(self):
        """Load, sync and save manifests the hard way.

        This test does not cover error scenarios. Instead, it shows how the
        individual functions in `manio` play together.

        This test does not load or save any files.

        """
        # Construct demo manifests in the same way as `load_files` would.
        dply = [mk_deploy(f"d_{_}", "nsfoo") for _ in range(10)]
        meta = [square.make_meta(_) for _ in dply]
        fdata_test_in = {
            "m0.yaml": [dply[0], dply[1], dply[2]],
            "m1.yaml": [dply[3], dply[4]],
            "m2.yaml": [dply[5]],
        }
        fdata_test_in = self.yamlfy(fdata_test_in)
        expected_manifests = {meta[_]: dply[_] for _ in range(6)}

        # ---------- PARSE YAML FILES ----------
        # Parse Yaml string, extract MetaManifest and compile new dict from it.
        # :: Dict[Filename:YamlStr] -> Dict[Filename:List[(MetaManifest, YamlDict)]]
        fdata_meta, err = manio.parse(fdata_test_in)
        assert err is False

        # Drop the filenames and create a dict that uses MetaManifests as keys.
        # :: Dict[Filename:List[(MetaManifest, YamlDict)]] -> Dict[MetaManifest:YamlDict]
        local_manifests, err = manio.unpack(fdata_meta)
        assert err is False

        # Verify that the loaded manifests are correct.
        assert local_manifests == expected_manifests

        # ---------- CREATE FAKE SERVER MANIFESTS ----------
        # Create a fake set of server manifests based on `expected_manifests`.
        # In particular, pretend that K8s supplied two additional manifests,
        # lacks two others and features one with different content.
        server_manifests = expected_manifests
        del expected_manifests

        server_manifests[meta[6]] = dply[6]  # add new one
        server_manifests[meta[7]] = dply[7]  # add new one
        del server_manifests[meta[3]], server_manifests[meta[5]]  # delete two
        server_manifests[meta[1]]["metadata"] = {"new": "label"}  # modify one

        # ---------- SYNC SERVER MANIFESTS BACK TO LOCAL YAML FILES ----------
        # Sync the local manifests to match those in the server.
        # * Upsert local with server values.
        # * Delete the manifests that do not exist on the server.
        # :: Dict[MetaManifests:YamlDict] -> Dict[Filename:List[(MetaManifest, YamlDict)]]
        updated_manifests, err = manio.sync(fdata_meta, server_manifests)
        assert err is False

        # Convert the data to YAML. The output would normally be passed to
        # `save_files` but here we will verify it directly (see below).
        # :: Dict[Filename:List[(MetaManifest, YamlDict)]] -> Dict[Filename:YamlStr]
        fdata_raw_new, err = manio.unparse(updated_manifests)
        assert err is False

        # Expected output after we merged back the changes (reminder: `dply[1]`
        # is different, `dply[{3,5}]` were deleted and `dply[{6,7}]` are new).
        # The new manifests must all end up in "_nsfoo.yaml" file because they
        # specify resources in the `nsfoo` namespace.
        expected = {
            "m0.yaml": [dply[0], server_manifests[meta[1]], dply[2]],
            "m1.yaml": [dply[4]],
            "_nsfoo.yaml": [dply[6], dply[7]],
        }
        expected = self.yamlfy(expected)
        assert fdata_raw_new == expected


class TestYamlManifestIOIntegration:
    """These integration tests all write files to temporary folders."""

    @classmethod
    def setup_class(cls):
        square.setup_logging(9)

    def test_load_save_files(self, tmp_path):
        """Basic file loading/saving tests."""
        # Demo file names and content.
        fnames = ("m0.yaml", "m1.yaml", "foo/m2.yaml", "foo/bar/m3.yaml")
        file_data = {fname: f"Data in {fname}" for fname in fnames}

        # Asking for non-existing files must return an error.
        assert manio.load_files(tmp_path, fnames) == RetVal(None, True)

        # Saving files to the temporary folder and loading them afterwards
        # again must work.
        assert manio.save_files(tmp_path, file_data) == RetVal(None, False)
        assert manio.load_files(tmp_path, fnames) == RetVal(file_data, False)

        # Manually verify the files.
        for fname in fnames:
            fp = tmp_path / fname
            assert fp.exists()
            assert fp.read_text() == file_data[fname]

        # Saving to non-writable (or non-existing) folder must fail.
        assert manio.save_files("/does/not/exist", file_data) == RetVal(None, True)

    def test_load_save_ok(self, tmp_path):
        """Basic test that uses the {load,save} convenience functions."""
        # Create two YAML files, each with multiple manifests.
        dply = [mk_deploy(f"d_{_}") for _ in range(10)]
        meta = [square.make_meta(mk_deploy(f"d_{_}")) for _ in range(10)]
        fdata_test_in = {
            "m0.yaml": [(meta[0], dply[0]), (meta[1], dply[1])],
            "foo/m1.yaml": [(meta[2], dply[2])],
        }
        del dply, meta

        # Save the test data, then load it back and verify.
        assert manio.save(tmp_path, fdata_test_in) == RetVal(None, False)
        assert manio.load(tmp_path) == RetVal(fdata_test_in, False)

        # Glob the folder and ensure it contains exactly the files specified in
        # the `fdata_test_in` dict.
        fnames_abs = {str(tmp_path / fname) for fname in fdata_test_in.keys()}
        assert set(str(_) for _ in tmp_path.rglob("*.yaml")) == fnames_abs

        # Create non-YAML files. The `load_files` function must skip those.
        (tmp_path / "delme.txt").touch()
        (tmp_path / "foo" / "delme.txt").touch()
        assert manio.load(tmp_path) == RetVal(fdata_test_in, False)

    def test_save_delete_stale_yaml(self, tmp_path):
        """`save_file` must remove all excess YAML files."""
        # Create two YAML files, each with multiple manifests.
        dply = [mk_deploy(f"d_{_}") for _ in range(10)]
        meta = [square.make_meta(mk_deploy(f"d_{_}")) for _ in range(10)]
        fdata_full = {
            "m0.yaml": [(meta[0], dply[0])],
            "m1.yaml": [(meta[1], dply[1])],
            "foo/m2.yaml": [(meta[2], dply[2])],
            "foo/m3.yaml": [(meta[3], dply[3])],
            "bar/m4.yaml": [(meta[4], dply[4])],
            "bar/m5.yaml": [(meta[5], dply[5])],
        }
        del dply, meta

        # Save and load the test data.
        assert manio.save(tmp_path, fdata_full) == RetVal(None, False)
        assert manio.load(tmp_path) == RetVal(fdata_full, False)

        # Save a reduced set of files. Compared to `fdata_full`, it is two
        # files short and a third one ("bar/m4.yaml") is empty.
        fdata_reduced = fdata_full.copy()
        del fdata_reduced["m0.yaml"]
        del fdata_reduced["foo/m3.yaml"]
        fdata_reduced["bar/m4.yaml"] = []

        # Verify that the files still exist from the last call to `save`.
        assert (tmp_path / "m0.yaml").exists()
        assert (tmp_path / "foo/m3.yaml").exists()
        assert (tmp_path / "bar/m4.yaml").exists()

        # Save and the reduced set.
        assert manio.save(tmp_path, fdata_reduced) == RetVal(None, False)

        # Load the data. It must neither contain the files we removed from the
        # dict above, nor "bar/m4.yaml" which contained an empty manifest list.
        del fdata_reduced["bar/m4.yaml"]
        assert manio.load(tmp_path) == RetVal(fdata_reduced, False)

        # Verify that the files physically do not exist anymore.
        assert not (tmp_path / "m0.yaml").exists()
        assert not (tmp_path / "foo/m3.yaml").exists()
        assert not (tmp_path / "bar/m4.yaml").exists()

    @mock.patch.object(manio, "load_files")
    def test_load_err(self, m_load, tmp_path):
        """Simulate an error in `load_files` function."""
        m_load.return_value = RetVal(None, True)
        assert manio.load(tmp_path) == RetVal(None, True)

    @mock.patch.object(manio, "unparse")
    def test_save_err(self, m_unparse, tmp_path):
        """Simulate an error in `unparse` function."""
        m_unparse.return_value = RetVal(None, True)
        assert manio.save(tmp_path, "foo") == RetVal(None, True)
