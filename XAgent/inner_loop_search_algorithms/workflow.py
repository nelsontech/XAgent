from XAgent.data_structure.node import ToolNode
from XAgent.data_structure.tree import TaskSearchTree
from XAgent.utils import ToolCallStatusCode
from XAgent.global_vars import config
from XAgent.inner_loop_search_algorithms.base_workflow import BaseInnerWorkFlow


class InnerWorkFlow(BaseInnerWorkFlow):
    def __init__(self, workflow_yml, config, tool_jsons, toolserver_interface):
        super().__init__(workflow_yml, config, tool_jsons, toolserver_interface)
        
    def run(self, 
            new_tree_node: ToolNode=None, 
            now_attempt_tree:TaskSearchTree=None,
            function_handler=None
        ):
        """
        Parameters:
        - new_tree_node: The starting node of the workflow.
        - now_attempt_tree: Current subtask tree.
        - task_handler: Task handler.
        - function_handler: Function Handler.
        """
        global_parameters =  new_tree_node.data["command"]["properties"]["args"]
        running_time_parameters = {}
        last_node = None
        for procedure_id, procedure_dict in enumerate(self.procedures):  
            procedure = procedure_dict["name"]
            input_parameters = {}
            needed_parameters = self.search_parameters(procedure)
            for param_name in needed_parameters:
                if param_name in global_parameters:
                    input_parameters[param_name] = global_parameters[param_name]
                elif param_name in running_time_parameters:
                    # TODO: If there is any needed parameters not in global parameters,
                    # how to choose from running time parameters. Currently specified in pre-defined yaml, 'legacy'.
                    input_parameters[param_name] = running_time_parameters[param_name]
                else:
                    raise RuntimeError(f"Can't find parameter {param_name} during workflow {self.workflow_config['name']}.")
            
            procedure_node = self.make_procedure_node(procedure, input_parameters)
            tool_output, tool_output_status_code, need_for_plan_refine, using_tools = function_handler.handle_tool_call(procedure_node)
            
            if procedure_id == 0:
                now_attempt_tree.make_father_relation(new_tree_node, procedure_node)
            else:
                now_attempt_tree.make_father_relation(last_node, procedure_node)
            
            if tool_output_status_code != ToolCallStatusCode.TOOL_CALL_SUCCESS:
                return f"Error in procedure {procedure}: {tool_output}", tool_output_status_code
            
            # specify the result of current workflow node, for the next node's input.
            save_parameter = procedure_dict["legacy"] 
            running_time_parameters[save_parameter] = using_tools["tool_output"] # use the origin tool output
            last_node = procedure_node
        return last_node, tool_output, tool_output_status_code, need_for_plan_refine, using_tools
    
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
    global_parameters = {
        "search_query":"Hello world", "goals_to_browse":"Hello world", "filepath":"./"
    }
    # workflow.run(global_parameters)
