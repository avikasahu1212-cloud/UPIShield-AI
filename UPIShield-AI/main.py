import random
import networkx as nx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="UPIShield - Module 2: Dependency & Cascade Engine")

class CascadeRequest(BaseModel):
    failed_node: str
    trials: int = 5000

class UPIDependencyGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self._build_topology()

    def _build_topology(self):
        # Define core entities in the UPI payment chain
        nodes = [
            "TPAP_App", 
            "Sponsor_Bank", 
            "NPCI_Switch", 
            "Remitter_Bank_A", 
            "Beneficiary_Bank_B", 
            "Status_Check_API", 
            "Payment_Gateway"
        ]
        self.graph.add_nodes_from(nodes)
        
        # Directed edges with failure transfer probabilities
        edges = [
            ("TPAP_App", "Sponsor_Bank", 0.95),
            ("Sponsor_Bank", "NPCI_Switch", 0.90),
            ("NPCI_Switch", "Remitter_Bank_A", 0.85),
            ("NPCI_Switch", "Beneficiary_Bank_B", 0.85),
            ("Remitter_Bank_A", "Status_Check_API", 0.75),
            ("Beneficiary_Bank_B", "Payment_Gateway", 0.80),
        ]
        for src, dst, weight in edges:
            self.graph.add_edge(src, dst, failure_transfer_prob=weight)

    def get_topology(self):
        return {
            "nodes": list(self.graph.nodes()),
            "edges": [{"source": u, "target": v, "probability": d["failure_transfer_prob"]} for u, v, d in self.graph.edges(data=True)]
        }

    def simulate_cascade(self, initial_failed_node: str, trials: int = 5000) -> dict:
        if initial_failed_node not in self.graph:
            raise HTTPException(status_code=404, detail=f"Node '{initial_failed_node}' not found in topology graph.")

        failure_counts = {node: 0 for node in self.graph.nodes()}
        
        for _ in range(trials):
            failed_set = {initial_failed_node}
            queue = [initial_failed_node]
            
            while queue:
                current = queue.pop(0)
                for successor in self.graph.successors(current):
                    if successor not in failed_set:
                        prob = self.graph[current][successor]['failure_transfer_prob']
                        if random.random() < prob:
                            failed_set.add(successor)
                            queue.append(successor)
            
            for node in failed_set:
                failure_counts[node] += 1
                
        # Calculate percentage probability of failure per node
        probabilities = {node: round((count / trials) * 100, 2) for node, count in failure_counts.items()}
        return {
            "initial_failure": initial_failed_node,
            "trials": trials,
            "cascade_probabilities": probabilities
        }

simulator = UPIDependencyGraph()

@app.get("/")
async def root():
    return {"message": "Module 2 Graph API is running successfully!"}

@app.get("/api/graph/topology")
async def fetch_topology():
    return simulator.get_topology()

@app.post("/api/graph/simulate-cascade")
async def run_cascade(request: CascadeRequest):
    return simulator.simulate_cascade(request.failed_node, request.trials)