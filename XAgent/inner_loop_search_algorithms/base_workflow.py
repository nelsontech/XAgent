import abc
import yaml
import json
import time
import requests
from colorama import Fore, Style
from XAgent.utils import ToolCallStatusCode
from XAgent.loggers.logs import logger
from XAgent.tool_call_handle import unwrap_tool_response
from XAgent.running_recorder import recorder


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
        
    def __str__(self) -> str:
        return self.workflow_config.workflow_name

    def status(self):
        return self.status

    def exec_single_node(self, command_name, arguments):
        command_result, tool_output_status_code, = self.toolserver_interface.execute_command_client(
            command_name,
            arguments,
        )
        """
        Basicall copy from XAgent/tool_call_handler.py, function handle_tool_call.
        """
        
        MAX_RETRY = 10
        retry_time = 0
        while retry_time<MAX_RETRY and tool_output_status_code == ToolCallStatusCode.TIMEOUT_ERROR and isinstance(command_result['detail'],dict) and 'type' in command_result['detail'] and command_result['detail']['type']=='retry':
            time.sleep(3)
            retry_time += 1
            command_result, tool_output_status_code, = self.toolserver_interface.execute_command_client(
                command_result['detail']['next_calling'],
                command_result['detail']['arguments'],
            )

        if tool_output_status_code == ToolCallStatusCode.TIMEOUT_ERROR and retry_time==MAX_RETRY:
            command_result = "Timeout and no content returned! Please check the content you submit!"

        if tool_output_status_code==ToolCallStatusCode.TOOL_CALL_SUCCESS:
            command_result = self.long_result_summary({'name':command_name,'arguments':arguments},command_result)

        result = f"Command {command_name} returned: " + f"{command_result}"

        # node.workspace_hash_id = output_hash_id
        if result is not None:
            logger.typewriter_log("SYSTEM: ", Fore.YELLOW, result)
        else:
            logger.typewriter_log(
                "SYSTEM: ", Fore.YELLOW, "Unable to execute command"
            )

        if tool_output_status_code == ToolCallStatusCode.TOOL_CALL_SUCCESS:
            color = Fore.GREEN
        elif tool_output_status_code == ToolCallStatusCode.SUBMIT_AS_SUCCESS:
            color = Fore.YELLOW
        elif tool_output_status_code == ToolCallStatusCode.SUBMIT_AS_FAILED:
            color = Fore.BLUE
        else:
            color = Fore.RED

        logger.typewriter_log(
            "TOOL STATUS CODE: ", Fore.YELLOW, f"{color}{tool_output_status_code.name}{Style.RESET_ALL}"
        )

        recorder.regist_tool_call(
            tool_name = command_name,
            tool_input = arguments,
            tool_output = command_result,
            tool_status_code = tool_output_status_code.name
        )

        return command_result, tool_output_status_code
