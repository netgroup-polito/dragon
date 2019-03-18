from collections import OrderedDict

import community
import networkx as nx
import nxmetis


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

        # if len(self.graph.nodes()) < 7:

        if n_clusters == 1:
            clustering = {node: 0 for node in self.graph.nodes()}
        else:
            try_resolution = 0.0

            if n_clusters > len(self.graph.nodes()):
                raise Exception("Too many clusters required")

            while True:
                clustering = community.best_partition(self.graph, resolution=try_resolution)
                if len(set(clustering.values())) == n_clusters:
                    break
                elif len(set(clustering.values())) < n_clusters or try_resolution > 1.1:
                    try_resolution = 0.0
                else:
                    try_resolution += 0.05
        '''
        else:
            options = nxmetis.MetisOptions()
            options.ptype = 1
            options.objtype = 1
            clusters = nxmetis.partition(self.graph, n_clusters, options=options)[1]
            clustering = {node: [i for i, cluster in enumerate(clusters) if node in cluster][0]
                          for node in self.graph.nodes()}
        '''
        return clustering