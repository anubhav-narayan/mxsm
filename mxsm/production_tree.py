from typing import Any, Tuple
from anytree import Node


class ProductionTree():
	def __init__(self, prod: dict | Node):
		if isinstance(prod, dict):
			def resolve_pdict(pdict, pre='PROD'):
				if isinstance(pdict, dict):
					rdict = {
						'name': pre,
						'children': []
					}
					if 'idepth' in pdict:
						rdict['idepth'] = pdict.pop('idepth')
					for x in pdict:
						rdict['children'].append(resolve_pdict(pdict[x], f"{x}"))
					return rdict
				elif isinstance(pdict, str):
					return {'name': pre, 'value': int(pdict, 16)}
				else:
					return {'name': pre, 'value': pdict}
			from anytree.importer import DictImporter
			self.importer = DictImporter(Node)
			self.__prod__ = self.importer.import_(resolve_pdict(prod))
		else:
			self.__prod__ = prod

	
	@classmethod
	def from_json(cls, prod_fh):
		import json
		pdict = json.load(prod_fh)['PROD']
		return cls(pdict)

	def __repr__(self) -> str:
		from anytree import RenderTree
		return str(RenderTree(self.__prod__))

	@property
	def root(self):
		return self.__prod__

	def get_production(self, fmt: str):
		from anytree.search import find_by_attr
		return ProductionTree(find_by_attr(self.__prod__, fmt))

	def search_path(self, path_fmt: str) -> Node:
		from anytree.resolver import Resolver
		resolver = Resolver('name')
		return resolver.get(self.root, path_fmt)

	def search_code(self, code: int) -> Tuple[Node]:
		from anytree.search import findall_by_attr
		return findall_by_attr(self.root, code, 'value')

	def __getitem__(self, fmt: str):
		return self.get_production(fmt)
