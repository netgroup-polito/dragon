from collections import OrderedDict

from community import community_louvain
import networkx as nx
#import tests.utils.nxmetis.nxmetis as nxmetis
import nxmetis
import sys


class Graph:
    """
    Here 'node' is a node of the graph, i.e., an sdo.
    """

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

        if len(self.topology.keys()) == 1:
            self.graph.add_nodes_from(self.topology.keys())

    def compute_clusters(self, n_clusters):
        if len(self.topology) == 0:
            return dict()

        if n_clusters == 1:
            clustering = {node: 0 for node in self.graph.nodes()}
        else:
            try_resolution = 0.0

            if n_clusters > len(self.graph.nodes()):
                raise Exception("Too many clusters required")

            attempt = 0
            best_clustering = None
            best_len_difference = sys.maxsize

            while attempt < 10:
                clustering = community_louvain.best_partition(self.graph, resolution=try_resolution)
                if len(set(clustering.values())) == n_clusters:
                    clusters = [{node for node in clustering if clustering[node] == i} for i in range(n_clusters)]
                    clusters_len = [len(c) for c in clusters]
                    len_difference = max(clusters_len) - min(clusters_len)
                    if len_difference < best_len_difference:
                        best_clustering = clustering
                        best_len_difference = len_difference
                        if len_difference <= 1:
                            break
                if len(set(clustering.values())) < n_clusters or try_resolution > 1.1:
                    try_resolution = 0.0
                    attempt += 1
                else:
                    try_resolution += 0.05
            clustering = best_clustering

        if clustering is None:
            # emergency algorithm:
            print("WARNING")
            options = nxmetis.MetisOptions()
            options.ptype = 1
            options.objtype = 1
            clusters = nxmetis.partition(self.graph, n_clusters, options=options)[1]
            clustering = {node: [i for i, cluster in enumerate(clusters) if node in cluster][0]
                          for node in self.graph.nodes()}
        return clustering

    def print_topology(self):
        print("-------- Topology ---------")
        for node, neighborhood in self.topology.items():
            print(node + " -> " + str(neighborhood))
        print("---------------------------")
