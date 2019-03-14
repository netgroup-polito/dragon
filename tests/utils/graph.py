from collections import OrderedDict

import community
import networkx as nx


class Graph:

    def __init__(self, topology, n):

        topology = OrderedDict(topology)
        topology = {node: topology[node] for i, node in enumerate(topology) if i < n}
        for node in topology:
            topology[node] = [neighbor for neighbor in topology[node] if neighbor in topology.keys()]

        self.topology = topology
        self.graph = nx.Graph()

        self.graph.add_edges_from([(node1, node2)
                                   for node1 in self.topology.keys()
                                  for node2 in self.topology[node1]])

    def compute_clusters(self, n_clusters):

        try_resolution = 0.0

        if n_clusters > len(self.graph.nodes()):
            raise Exception("Too many clusters required")

        while True:
            clustering = community.best_partition(self.graph, resolution=try_resolution)
            if len(set(clustering.values())) == n_clusters:
                break
            elif len(set(clustering.values())) < n_clusters:
                try_resolution = 0.0
            else:
                try_resolution += 0.1

        return clustering
