import generate_template
import concat_index_pattern_fields
import yaml
import os
import io
import tempfile
import supported_versions as supported
import common_test_support

class CompareAgainstReleasedPatternsTestCase(common_test_support.CommonTestSupport):

    _index_pattern_viaq_os = "https://github.com/ViaQ/elasticsearch-templates/releases/download/0.0.12/com.redhat.viaq-openshift.index-pattern.json"

    # The following namespaces should be the same as those listed in "templates/Makefile::${INDEX_PATTERN_DIRS}"
    _template_namespaces = ['openshift', 'collectd_metrics']

    def test_index_pattern_without_fields_field(self):
        """This test compare JSON of generated index pattern and released one
        except it removes the 'fields' field first. This is to ensure the rest
        of the index pattern is the same. There are other tests that compare
        just the content of the 'fields' field separately.
        """

        generated_json = self._generate_index_pattern(self._template_namespaces[0], supported._es2x)

        _json = self._from_string_to_json(generated_json)
        del _json["fields"]
        generated_index_pattern = self._sort(_json)

        # ---- wget
        json_data = self._wget(self._index_pattern_viaq_os)

        # Fix downloaded data:
        # ======================
        # We need to clean some diffs that we know exists today but they are either
        # fine to ignore or there is an open ticket that has fix pending.

        #  - see https://github.com/ViaQ/elasticsearch-templates/issues/77
        del json_data["description"]
        # ======================

        del json_data["fields"]

        released_index_pattern = self._sort(json_data)

        # Compare index patterns without the "fields" field.
        self.assertEqual(released_index_pattern, generated_index_pattern)

    def test_index_pattern_fields_field_only(self):
        """This test generates index patterns for individual namespaces
        and then use the concat utility to create the cumulative index pattern file
        that is then compared with the released version.
        We compare only the "fields" field.
        """
        generated_fields = None
        es_version = supported._es2x
        index_pattern_suffix = 'index-pattern.json'
        match_index_pattern = '*'+index_pattern_suffix

        # Create temp directory to store generated index patterns to (and load from also).
        # See https://docs.python.org/3/library/tempfile.html#examples
        with tempfile.TemporaryDirectory() as tmpdirname:
            print('created temporary folder', tmpdirname)

            for namespace in self._template_namespaces:
                generated_json = self._generate_index_pattern(namespace, es_version)
                file = io.open(os.path.join(tmpdirname, ".".join([namespace, es_version, index_pattern_suffix])), 'w')
                file.write(generated_json)
                file.write('\n')
                file.close()

            with io.open(os.path.join(tmpdirname, "cumulative_index_pattern.json"), mode='w', encoding='utf8') as cumulative_file:
                individual_files = concat_index_pattern_fields.filter_index_pattern_files(tmpdirname, match_index_pattern, es_version)

                print("All files in temporary folder:")
                self._print_files_in_folder(tmpdirname)

                print("The following files will be used to populate cumulative file:")
                print(individual_files)

                concat_index_pattern_fields.concatenate_index_pattern_files(individual_files, cumulative_file)
                print("Cumulative file populate, closing for write")
                cumulative_file.close()

                print("All files in temporary folder:")
                self._print_files_in_folder(tmpdirname)

                cumulative_json = self._json_from_file(os.path.join(tmpdirname, cumulative_file.name))
                generated_fields = self._from_string_to_json(cumulative_json["fields"])

        # Exit the context of temporary folder. This will remove also all the content in it.
        # generated_index_pattern = self._sort(_json)

        # ---- wget
        json_data = self._wget(self._index_pattern_viaq_os)
        released_fields = self._from_string_to_json(json_data["fields"])

        # Fix downloaded data:
        # ======================
        # We need to clean some diffs that we know exists today but they are either
        # fine to ignore or there is an open ticket that has fix pending.

        #  We need to explicitly override doc_values to false for text type fields.
        #  - see https://github.com/ViaQ/elasticsearch-templates/pull/70#issuecomment-360704220
        list(filter(lambda i: i["name"] == "aushape.error", released_fields))[0]["doc_values"] = False
        list(filter(lambda i: i["name"] == "kubernetes.container_name", released_fields))[0]["doc_values"] = False

        #  - We changed how 'namespace_name' is configured in namespaces/_default_.yml.
        #    TODO: We need to review how those changes need to be translated into Kibana index pattern.
        #    This does not look correct to me.
        list(filter(lambda i: i["name"] == "namespace_name", released_fields))[0]["analyzed"] = True

        # ======================

        generated_fields.sort(key=lambda item: item["name"])
        released_fields.sort(key=lambda item: item["name"])

        # print("released_fields ==========")
        # print(self._sort(released_fields))
        # print("generated_fields ==========")
        # print(self._sort(generated_fields))

        # Compare the "fields"
        self.assertEqual(self._sort(released_fields), self._sort(generated_fields))

    def _generate_index_pattern(self, template_namespace, es_version):
        # The convention is that each namespace folder contains "template.yml" file, except
        # the "openshift" namespace which contains two files (project and operations).
        # We use the operations in this test.
        template_file_name = "template.yml"
        if template_namespace == "openshift":
            template_file_name = "template-operations.yml"

        # args = self.parser.parse_args(['../templates/test/template-test.yml', '../namespaces/'])
        args = self.parser.parse_args(['../templates/'+template_namespace+'/'+template_file_name, '../namespaces/'])

        with io.open(args.template_definition, 'r') as input_template:
            template_definition = yaml.load(input_template)

        # We need to update paths 'cos this test is started from different folder
        template_definition['skeleton_path'] = '../templates/skeleton.json'
        template_definition['skeleton_index_pattern_path'] = '../templates/skeleton-index-pattern.json'

        output = io.open(os.devnull, 'w')
        output_index_pattern = io.StringIO()
        generate_template.object_types_to_template(template_definition,
                                                   output, output_index_pattern,
                                                   es_version,
                                                   args.namespaces_dir)

        generated_json = output_index_pattern.getvalue()

        output.close()
        output_index_pattern.close()

        return generated_json

    def _print_files_in_folder(self, dir):
        for _file in os.listdir(dir):
            print(" -",_file, os.stat(os.path.join(dir,_file)).st_size, "bytes")
