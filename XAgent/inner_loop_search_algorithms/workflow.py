from XAgent.utils import ToolCallStatusCode
from XAgent.global_vars import config
from XAgent.inner_loop_search_algorithms.base_workflow import BaseInnerWorkFlow


class InnerWorkFlow(BaseInnerWorkFlow):
    def __init__(self, workflow_yml, config, tool_jsons, toolserver_interface):
        super().__init__(workflow_yml, config, tool_jsons, toolserver_interface)
        
    def run(self, **kwargs):
        """
        Parameters:
        - kwargs: should contains global parameters that might be used within the workflow.
        """
        running_time_parameters = {}
        for procedure_id, procedure_dict in enumerate(self.procedures):
            procedure = procedure_dict["name"]
            input_parameters = {}
            needed_parameters = self.search_parameters(procedure)
            for param_name in needed_parameters:
                if param_name in kwargs:
                    input_parameters[param_name] = kwargs[param_name]
                elif param_name in running_time_parameters:
                    # TODO: If there is any needed parameters not in global parameters,
                    # how to choose from running time parameters. Currently specified in pre-defined yaml, 'legacy'.
                    input_parameters[param_name] = running_time_parameters[param_name]
                else:
                    raise RuntimeError(f"Can't find parameter {param_name} during workflow {self.workflow_config['name']}.")
            
            command_result, tool_output_status_code = self.exec_single_node(procedure, input_parameters)
            
            if tool_output_status_code != ToolCallStatusCode.TOOL_CALL_SUCCESS:
                return f"Error in procedure {procedure}: {command_result}", tool_output_status_code
            # specify the result of current workflow node, store in what name
            save_parameter = procedure_dict["legacy"] 
            running_time_parameters[save_parameter] = command_result

        return command_result, tool_output_status_code
    
    def search_parameters(self, procedure: str) -> list:
        # print(self.tool_jsons[procedure])
        return self.tool_jsons[procedure]


if __name__ == "__main__":
    from XAgent.tool_call_handle import ToolServerInterface, FunctionHandler
    toolserver_interface = ToolServerInterface()
    function_handler = FunctionHandler()
    subtask_functions, tool_functions_description_list = function_handler.get_functions(config)
    print(function_handler.avaliable_tools_description_list)
    workflow = InnerWorkFlow(workflow_yml="information_collection.yml", config=config, tool_jsons=tool_functions_description_list, toolserver_interface=toolserver_interface)
    workflow.run(search_query="Hello world", goals_to_browse="Hello world", filepath="./")
