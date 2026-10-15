"""Frozen declarations fail named; no repository files are modified by controls."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import graph_registry


class Registry(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((graph_registry.ROOT/"tools/eval/graphs.json").read_text(encoding="utf-8"))

    def test_current_generated_output(self):
        actual=(graph_registry.ROOT/"src/eval/graph_registry.inc").read_text(encoding="utf-8")
        self.assertEqual(graph_registry.render(self.config),actual)

    def test_unknown_or_missing_graph_is_named(self):
        config=copy.deepcopy(self.config);config["unclassified"]={}
        with self.assertRaisesRegex(ValueError,"eval_graph_unclassified.*unclassified"):
            graph_registry.render(config)
        del self.config["medium"]
        with self.assertRaisesRegex(ValueError,"eval_graph_unclassified.*medium"):
            graph_registry.render(self.config)

    def test_every_declared_field_is_frozen(self):
        for graph in ("full","small","medium"):
            for field in self.config[graph]:
                with self.subTest(graph=graph,field=field):
                    config=copy.deepcopy(self.config);config[graph][field]+=1
                    with self.assertRaisesRegex(ValueError,"eval_graph_declaration_changed:"+graph):
                        graph_registry.render(config)

    def test_extra_field_refuses(self):
        self.config["small"]["extra"]=0
        with self.assertRaisesRegex(ValueError,"eval_graph_fields:small"):
            graph_registry.render(self.config)


if __name__=="__main__":unittest.main()
