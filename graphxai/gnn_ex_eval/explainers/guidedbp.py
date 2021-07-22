import torch
import torch.nn.functional as F

from torch_geometric.nn import MessagePassing
from torch_geometric.utils import k_hop_subgraph

from .utils.base_explainer import WalkBase

def clip_hook(grad):
    # Apply ReLU activation to gradient
    return torch.clamp(grad, min=0)#F.relu(grad)

def matching_explanations(nodes, exp):
    # Get explanation matching to subgraph nodes
    new_exp = torch.zeros(len(exp))
    list_nodes = nodes.tolist()
    for i in range(len(exp)):
        if i in nodes:
            new_exp[i] = exp[i]

    return new_exp.tolist()

class GuidedBP(WalkBase):

    def __init__(self, model, criterion = F.cross_entropy):
        '''
        Args:
            model (torch.nn.Module): model on which to make predictions
            device: device on which model is to run
            criterion (PyTorch Loss Function): loss function used to train the model.
                Needed to pass gradients backwards in the network to obtain gradients.
        '''
        super(WalkBase, self).__init__(model)
        self.model = model
        self.criterion = criterion

        self.L = len([module for module in self.model.modules() if isinstance(module, MessagePassing)])

        self.registered_hooks = []

    def get_explanation_node(self, x: torch.Tensor, node_idx: int, labels: torch.Tensor, 
        edge_index: torch.Tensor, forward_args: tuple = None) -> torch.Tensor:
        '''
        Get Guided Backpropagation explanation for one node in the graph
        Args:
            x (torch.tensor): tensor of node features from the entire graph
            node_idx (int): node index for which to explain a prediction around
            labels (torch.Tensor): labels correspond to each node's classification
            edge_index (torch.tensor): edge_index of entire graph
            forward_args (tuple, optional): additional arguments to model.forward 
                beyond x and edge_index. (default: :obj:`None`)
        '''

        # Run whole-graph prediction:
        x.requires_grad = True

        # Perform the guided backprop:
        xhook = x.register_hook(clip_hook)
        
        self.model.zero_grad()
        pred = self.__forward_pass(x, edge_index, forward_args)
        loss = self.criterion(pred, labels)
        self.__apply_hooks()
        loss.backward()
        self.__rm_hooks()

        xhook.remove() # Remove hook from x

        graph_exp = x.grad

        #graph_exp = torch.flatten(x.grad).tolist()

        khop_info = k_hop_subgraph(node_idx = node_idx, num_hops = self.L, edge_index = edge_index)
        subgraph_nodes = khop_info[0]

        # Set explanations to zero, fill in appropriate amounts:
        filtered_exp = torch.zeros(graph_exp.shape)
        for i in range(filtered_exp.shape[0]):
            if i in subgraph_nodes:
                filtered_exp[i,:] = graph_exp[i,:]

        return filtered_exp, khop_info

    def get_explanation_graph(self, x: torch.Tensor, label: torch.Tensor, edge_index: torch.Tensor, 
        forward_args: tuple = None) -> torch.Tensor:
        '''
        Explain a whole-graph prediction with Guided Backpropagation

        Args:
            x (torch.tensor): tensor of node features from the entire graph
            label (int): label for which to compute Grad-CAM against
            edge_index (torch.tensor): edge_index of entire graph
            forward_args (tuple, optional): additional arguments to model.forward 
                beyond x and edge_index. (default: :obj:`None`)        
        '''

        # Run whole-graph prediction:
        x.requires_grad = True

        # Perform the guided backprop:
        xhook = x.register_hook(clip_hook)
        
        self.model.zero_grad()
        pred = self.__forward_pass(x, edge_index, forward_args)
        loss = self.criterion(pred, label)
        self.__apply_hooks()
        loss.backward()
        self.__rm_hooks()

        xhook.remove() # Remove hook from x

        return x.grad

    def __apply_hooks(self):
        self.registered_hooks = []
        for p in self.model.parameters():
            h = p.register_hook(clip_hook)
            self.registered_hooks.append(h)

    def __rm_hooks(self):
        for h in self.registered_hooks:
            h.remove()
        self.registered_hooks = []
    
    def __forward_pass(self, x, edge_index, forward_args):
        #@torch.enable_grad()
        # Forward pass:
        self.model.eval()
        self.__apply_hooks()
        if forward_args is None:
            pred = self.model(x, edge_index)
        else:
            pred = self.model(x, edge_index, *forward_args)

        return pred