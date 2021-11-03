import torch
import random
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
from types import MethodType
from typing import Optional, Callable
from functools import partial
from torch_geometric.utils import k_hop_subgraph, to_undirected

from ..synthetic_dataset import ShapeGraph
from graphxai.utils.nx_conversion import khop_subgraph_nx
from graphxai import Explanation
from ..utils.shapes import *
from graphxai.datasets.feature import make_structured_feature
from graphxai.datasets.utils.graph_build import build_bound_graph

class BAShapes(ShapeGraph):
    '''
    BA Shapes dataset with keyword arguments for different planting, 
        insertion, labeling, and feature generation methods

    ..note:: Flag and circle shapes not yet implemented

    Args:
        num_hops (int): Number of hops for each node's enclosing 
            subgraph. Should correspond to number of graph convolutional
            layers in GNN. 
        n (int): For global planting method, corresponds to the total number of 
            nodes in graph. If using local planting method, corresponds to the 
            starting number of nodes in graph.
        m (int): Number of edges per node in graph.
        num_shapes (int): Number of shapes for given planting strategy.
            If planting strategy is global, total number of shapes in
            the graph. If planting strategy is local, number of shapes
            per num_hops - hop neighborhood of each node.
        shape (str, optional): Type of shape to be inserted into graph.
            Options are `'house'`, `'flag'`, `'circle'`, and `'multiple'`. 
            If `'multiple'`, random shapes are generated to insert into 
            the graph.
            (:default: :obj:`'house'`)
        graph_construct_strategy (str, optional): Type of insertion strategy for 
            each motif. Options are `'plant'` or `'staple'`.
            (:default: :obj:`'plant'`)
        shape_insert_strategy (str, optional): How to decide where shapes are 
            planted. 'global' method chooses random nodes from entire 
            graph. 'local' method enforces a lower bound on number of 
            shapes in the (num_hops)-hop neighborhood of each node. 
            'neighborhood upper bound' enforces an upper-bound on the 
            number of shapes per num_hops-hop neighborhood. 'bound_12' 
            enforces that all nodes in the graph are either in 1 or 2
            houses. 
            (:default: :obj:`'global'`)
        feature_method (str, optional): How to generate node features.
            Options are `'network stats'` (features are network statistics),
            `'gaussian'` (features are random gaussians), 
            `'gaussian_lv` (gaussian latent variables), and 
            `'onehot'` (features are random one-hot vectors) 
            (:default: :obj:`'network stats'`)
        labeling_method (str, optional): Rule of how to label the nodes.
            Options are `'feature'` (only label based on feature attributes), 
            `'edge` (only label based on edge structure), 
            `'edge and feature'` (label based on both feature attributes
            and edge structure). (:default: :obj:`'edge and feature'`)

        kwargs: Additional arguments
            shape_upper_bound (int, Optional): Number of maximum shapes
                to add per num_hops-hop neighborhood in the 'neighborhood
                upper bound' planting policy.
    '''

    def __init__(self, 
        num_hops: int, 
        n: int, 
        m: int, 
        num_shapes: int, 
        shape: Optional[str] = 'house',
        seed: Optional[int] = None,
        graph_construct_strategy: Optional[str] = 'plant',
        shape_insert_strategy: Optional[str] = 'global',
        feature_method: Optional[str] = 'network stats',
        labeling_method: Optional[str] = 'edge and feature',
        **kwargs):

        self.n = n
        self.m = m
        self.seed = seed

        self.feature_method = feature_method.lower()
        self.labeling_method = labeling_method.lower()
        if self.labeling_method == 'feature and edge':
            self.labeling_method = 'edge and feature'

        if shape_insert_strategy == 'neighborhood upper bound' and num_shapes is None:
            num_shapes = n # Set to maximum if num_houses left at None

        insert_shape = None
        self.shape_name = shape.lower()
        if self.shape_name == 'house':
            insert_shape = house
        elif self.shape_name == 'flag':
            pass
        elif self.shape_name == 'circle':
            insert_shape = pentagon # 5-member ring

        if self.shape_name == 'random':
            # random_shape imported from utils.shapes
            self.get_shape = partial(random_shape, n=3) 
            # Currenlty only support for 3-member shape bank (n=3)
        else:
            self.get_shape = lambda: (insert_shape, 1)

        if shape_insert_strategy.lower() == 'bound_12':
            assert self.shape_name != 'random', 'Multiple shapes not yet supported for bounded graph'

        y_before_x = False
        if self.feature_method == 'gaussian_lv':
            y_before_x = True

        super().__init__(
            name='BAHouses', 
            num_hops=num_hops,
            num_shapes = num_shapes,
            graph_construct_strategy = graph_construct_strategy,
            shape_insert_strategy = shape_insert_strategy,
            insertion_shape = insert_shape,
            y_before_x = y_before_x,
            **kwargs
        )

    def init_graph(self):
        '''
        Returns a Barabasi-Albert graph with desired parameters
        '''
        if self.shape_insert_strategy == 'bound_12':
            self.G = build_bound_graph(
                shape = house, 
                num_subgraphs = 10, 
                inter_sg_connections = 1,
                prob_connection = 1,
                num_hops = self.num_hops,
                base_graph = 'ba',
                )
        else:
            self.G = nx.barabasi_albert_graph(self.n, self.m, seed = self.seed)

    def feature_generator(self):
        '''
        Returns function to generate features for one node_idx
        '''
        if self.feature_method == 'network stats':
            deg_cent = nx.degree_centrality(self.G)
            def get_feature(node_idx):
                return torch.tensor([self.G.degree[node_idx], 
                    nx.clustering(self.G, node_idx), 
                    deg_cent[node_idx]]).float()

        elif self.feature_method == 'gaussian':
            def get_feature(node_idx):
                # Random random Gaussian feature vector:
                return torch.normal(mean=0, std=1.0, size = (3,))

        elif self.feature_method == 'onehot':
            def get_feature(node_idx):
                # Random one-hot feature vector:
                feature = torch.zeros(3)
                feature[random.choice(range(3))] = 1
                return feature

        elif self.feature_method == 'gaussian_lv':
            x, self.feature_imp_true = make_structured_feature(self.yvals, n_features = 10,
                n_informative = (torch.unique(self.yvals).shape[0]) * 2, seed = self.seed)

            Gitems = list(self.G.nodes.items())
            node_map = {Gitems[i][0]:i for i in range(self.G.number_of_nodes())}

            def get_feature(node_idx):
                return x[node_map[node_idx],:]
        
        else:
            raise NotImplementedError(f'{self.feature_method} feature method not supported')

        return get_feature

    def labeling_rule(self):
        '''
        Labeling rule for each node
        '''

        # avg_ccs = np.mean([self.G.nodes[i]['x'][1] for i in self.G.nodes])
        
        # def get_label(node_idx):
        #     # Count number of houses in k-hop neighborhood
        #     # subset, _, _, _ = k_hop_subgraph(node_idx, self.num_hops, self.graph.edge_index)
        #     # shapes = self.graph.shape[subset]
        #     # num_houses = (torch.unique(shapes) > 0).nonzero(as_tuple=True)[0]
        #     khop_edges = nx.bfs_edges(self.G, node_idx, depth_limit = self.num_hops)
        #     nodes_in_khop = set(np.unique(list(khop_edges))) - set([node_idx])
        #     num_unique_houses = len(np.unique([self.G.nodes[ni]['shape'] for ni in nodes_in_khop if self.G.nodes[ni]['shape'] > 0 ]))
        #     # Enfore logical condition:
        #     return torch.tensor(int(num_unique_houses == 1 and self.G.nodes[node_idx]['x'][0] > 1), dtype=torch.long)


        if self.labeling_method == 'edge':
            # Label based soley on edge structure
            # Based on number of houses in neighborhood
            if self.shape_name == 'random':
                def get_label(node_idx):
                    nodes_in_khop = khop_subgraph_nx(node_idx, self.num_hops, self.G)
                    # For now, sum motif id's in k-hop (min is 0 for no motifs)
                    motif_in_khop = sum(np.unique([self.G.nodes[ni]['motif_id'] for ni in nodes_in_khop]))
                    return torch.tensor(motif_in_khop, dtype=torch.long)
            else:
                if self.shape_insert_strategy == 'bound_12':
                    node_labels = [d['shapes_in_khop'] - 1 for _, d in self.G.nodes(data=True)]
                    Gitems = list(self.G.nodes.items())
                    node_map = {Gitems[i][0]:i for i in range(self.G.number_of_nodes())}
                    def get_label(node_idx):
                        return torch.tensor(node_labels[node_map[node_idx]], dtype=torch.long)

                else:
                    def get_label(node_idx):
                        nodes_in_khop = khop_subgraph_nx(node_idx, self.num_hops, self.G)
                        num_unique_houses = len(np.unique([self.G.nodes[ni]['shape'] \
                            for ni in nodes_in_khop if self.G.nodes[ni]['shape'] > 0 ]))
                        return torch.tensor(int(num_unique_houses == 1), dtype=torch.long)

        elif self.labeling_method == 'feature':
            # Label based solely on node features
            # Based on if feature[1] > median of all nodes
            max_node = len(list(self.G.nodes))
            node_attr = nx.get_node_attributes(self.G, 'x')
            x1 = [node_attr[i][1] for i in range(max_node)]
            med1 = np.median(x1)
            def get_label(node_idx):
                return torch.tensor(int(x1[node_idx] > med1), dtype=torch.long)

        elif self.labeling_method == 'edge and feature':
            # Calculate median (as for feature):
            max_node = len(list(self.G.nodes))
            node_attr = nx.get_node_attributes(self.G, 'x')
            x1 = [node_attr[i][1] for i in range(max_node)]
            med1 = np.median(x1)

            def get_label(node_idx):
                nodes_in_khop = khop_subgraph_nx(node_idx, self.num_hops, self.G)
                num_unique_houses = len(np.unique([self.G.nodes[ni]['shape'] \
                    for ni in nodes_in_khop if self.G.nodes[ni]['shape'] > 0 ]))
                return torch.tensor(int(num_unique_houses == 1 and x1[node_idx] > med1), dtype=torch.long)

        else:
            raise NotImplementedError() 
                
        return get_label

    def explanation_generator(self):

        # Label node and edge imp based off of each node's proximity to a house

        if self.labeling_method == 'edge':
            def exp_gen(node_idx):

                if self.feature_method == 'gaussian_lv':
                    # Set feature_imp to mask generated earlier:
                    feature_imp = self.feature_imp_true
                else:
                    raise NotImplementedError('Need to define node importance for other terms')

                # Tag all nodes in houses in the neighborhood:
                khop_nodes = khop_subgraph_nx(node_idx, self.num_hops, self.G)
                node_imp = torch.tensor([self.G.nodes[i]['shape'] for i in khop_nodes], dtype=torch.double)

                khop_info = k_hop_subgraph(
                    node_idx,
                    num_hops = self.num_hops,
                    edge_index = to_undirected(self.graph.edge_index)
                )

                # Get edge importance based on edges between any two nodes in motif
                in_motif = node_imp.nonzero(as_tuple=True)[0]
                edge_imp = torch.zeros(khop_info[1].shape[1], dtype=torch.double)
                for i in range(khop_info[1].shape[1]):
                    if khop_info[1][0,i] in in_motif and khop_info[1][1,i] in in_motif:
                        edge_imp[i] = 1

                exp = Explanation(
                    feature_imp=feature_imp,
                    node_imp = node_imp,
                    edge_imp = edge_imp,
                    node_idx = node_idx
                )

                exp.set_enclosing_subgraph(khop_info)
                # exp.set_whole_graph(khop_info[0], khop_info[1])
                exp.set_whole_graph(x = self.x, edge_index = self.graph.edge_index)
                return exp
        else:
            def exp_gen(node_idx):
                return None
        return exp_gen

    def visualize(self, shape_label = False):
        '''
        Args:
            shape_label (bool, optional): If `True`, labels each node according to whether
            it is a member of an inserted motif or not. If `False`, labels each node 
            according to its y-value. (:default: :obj:`True`)
        '''

        Gitems = list(self.G.nodes.items())
        node_map = {Gitems[i][0]:i for i in range(self.G.number_of_nodes())}

        if shape_label:
            y = [int(self.G.nodes[i]['shape'] > 0) for i in range(self.num_nodes)]
        else:
            ylist = self.graph.y.tolist()
            y = [ylist[node_map[i]] for i in self.G.nodes]

        node_weights = {i:node_map[i] for i in self.G.nodes}

        pos = nx.kamada_kawai_layout(self.G)
        _, ax = plt.subplots()
        nx.draw(self.G, pos, node_color = y, labels = node_weights, ax=ax)
        ax.set_title('BA Houses')
        plt.tight_layout()
        plt.show()

if __name__ == '__main__':
    class Hyperparameters:
        num_hops = 1
        n = 5000
        m = 1
        num_shapes = None
        shape_insert_strategy = 'neighborhood upper bound'
        shape_upper_bound = 1
        labeling_method = 'edge'

    hyp = Hyperparameters
    bah = BAShapes(**args, feature_method = 'gaussian')
    
    args = {key:value for key, value in hyp.__dict__.items() if not key.startswith('__') and not callable(value)}

    bah.visualize()