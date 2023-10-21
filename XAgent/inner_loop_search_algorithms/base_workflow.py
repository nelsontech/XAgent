import abc
import yaml
import json
from colorama import Fore, Style
from XAgent.data_structure.node import ToolNode
from XAgent.agent.summarize import summarize_action,summarize_plan
from XAgent.loggers.logs import logger


class BaseInnerWorkFlow(metaclass = abc.ABCMeta):
    def __init__(self, workflow_yml, config, tool_jsons, toolserver_interface):
        """
        Initializes the BaseInnerWorkFlow class with necessary configurations.
        
        Parameters:
        - workflow_yml (str): Path to the YAML file that contains the pre-defined workflow.
                             This file outlines the structure and sequence of the workflow steps.
                             
        - config (Config): Global configuration object of XAgent. This object contains 
                           necessary configurations that are essential for executing workflows.
                           
        - tool_jsons (list): A list containing JSON objects. Each JSON object holds the 
                             necessary information required for function calls to the available tools.
                             
        - toolserver_interface (object): An instance of the toolserver, which is initialized 
                                         in main.py. This interface facilitates interactions 
                                         with the toolserver during workflow execution.                          
        """
        logger.typewriter_log(
            f"Constructing an inner loop workflow.",
            Fore.YELLOW,
            self.__class__.__name__,
        )
        self.config = config
        self.workflow_config = yaml.load(open(workflow_yml), Loader=yaml.Loader)
        self.toolserver_interface = toolserver_interface
        self.procedures = self.workflow_config["procedures"]
        self.tool_jsons = {}
        for tool_json in tool_jsons:
            self.tool_jsons[tool_json["name"]] = tool_json["parameters"]["required"]
        self.workflow_json = self.make_function_call_json()
        
    def __str__(self) -> str:
        return self.workflow_config.workflow_name

    def status(self):
        return self.status

    def make_function_call_json(self):
        workflow_json = {
            "name": self.workflow_config["name"],
            "description": self.workflow_config["description"],
            "parameters": self.workflow_config["parameters"]
        }
        return workflow_json

    def make_procedure_node(self, procedure, input_parameters):
        procedure_node = ToolNode()
        procedure_node.data["content"] = f"Executing procedure {procedure}."
        procedure_node.data["command"]["properties"]["name"] = procedure
        procedure_node.data["command"]["properties"]["args"] = input_parameters
        return procedure_node
    
    def summary_actions(self, now_node: ToolNode, now_dealing_task):
        action_process = now_node.process
        if self.config.enable_summary:
            terminal_task_info = summarize_plan(
                now_dealing_task.to_json())
        else:
            terminal_task_info = json.dumps(
                now_dealing_task.to_json(), indent=2, ensure_ascii=False)
        if self.config.enable_summary:
            action_process = summarize_action(
                action_process, terminal_task_info)
        return action_process