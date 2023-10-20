import json
import json5

from typing import List
from colorama import Fore, Style
from copy import deepcopy

from XAgent.loggers.logs import logger
from XAgent.workflow.base_query import BaseQuery
from XAgent.global_vars import agent_dispatcher, vector_db_interface
from XAgent.utils import TaskSaveItem, RequiredAbilities, PlanOperationStatusCode, TaskStatusCode
from XAgent.message_history import Message
from XAgent.data_structure.plan import Plan
from XAgent.ai_functions import  function_manager
from XAgent.running_recorder import recorder
from XAgent.tool_call_handle import toolserver_interface
from XAgent.agent.summarize import summarize_plan
from XAgent.config import CONFIG

def plan_function_output_parser(function_output_item: dict) -> Plan:
    subtask_node = TaskSaveItem()
    subtask_node.load_from_json(function_output_item=function_output_item)
    subplan = Plan(subtask_node)
    return subplan


def flatten_tree(root):
    leaf_nodes:List[dict] = []

    def traverse(node):
        if "subtask" in node:
            for subtask_node in node["subtask"]:
                traverse(subtask_node)
        else:
            leaf_nodes.append(node)

    traverse(root)
    for leaf in leaf_nodes:
        if 'tool_call_process' in leaf:
            leaf.pop("tool_call_process")
    return leaf_nodes


def change_db_retrieve_to_reference(query):
    res = vector_db_interface.search_similar_sentences(query, "whole_workflow")
    res = json.loads(res["matches"][0]["metadata"]["text"])

    # flatten the tree to get all the leaves
    wanted_res = flatten_tree(res)
    # Maintain the original tree but only use the first level
    # wanted_res = res["subtask"]
    
    ref_plan = {"query": res["goal"], 'task_id': "1"}
    # begin to handle subtask
    sub_plans = []
    cur_id = 0
    for subtask in wanted_res:
        cur_id += 1
        # Typo in "execute"!
        status = "FAIL" if subtask["exceute_status"] == "SPLIT" else subtask["exceute_status"]
        status = "UNKNOWN" if status != "SUCCESS" and status != "FAIL" else status
        sub_plan = {"subtask name": subtask["name"], "goal": {"goal": subtask["goal"], "criticsim": subtask["prior_plan_criticsim"]}, "milestones": subtask["milestones"], "task_id": f"1.{cur_id}", "execute_status": status, "suggestion": "N/A"}
        if status == "SUCCESS":
            sub_plan["suggestion"] = "This subtask and milestones are resonable and could be successfully achieved. You can take this subtask as reference."
        elif "submit_result" in subtask:
            sub_plan["suggestion"] = subtask["submit_result"]["args"]["suggestions_for_latter_subtasks_plan"]["reason"]
        sub_plans.append(sub_plan)
    # Add the subplans finally as reference
    ref_plan["subtasks"] = sub_plans

    return json.dumps(ref_plan, indent=2, ensure_ascii=False)


def refine_db_retrieve_to_reference(goal):
    res = vector_db_interface.search_similar_sentences(goal, "workflow")
    res = json.loads(res["matches"][0]["metadata"]["text"])

    # flatten the tree to get all the leaves
    wanted_res = flatten_tree(res)
    # Maintain the original tree but only use the first level
    # wanted_res = res["subtask"]
    
    ref_plan = {"reference_task_name": res["name"], "reference_task_goal": res["goal"], 'task_id': "1"}

    # begin to handle subtask (same process)
    sub_plans = []
    cur_id = 0
    for subtask in wanted_res:
        cur_id += 1
        # Typo in "execute"!
        status = "FAIL" if subtask["exceute_status"] == "SPLIT" else subtask["exceute_status"]
        status = "UNKNOWN" if status != "SUCCESS" and status != "FAIL" else status
        sub_plan = {"subtask name": subtask["name"], "goal": {"goal": subtask["goal"], "criticsim": subtask["prior_plan_criticsim"]}, "milestones": subtask["milestones"], "task_id": f"1.{cur_id}", "execute_status": status, "suggestion": "N/A"}
        if status == "SUCCESS":
            sub_plan["suggestion"] = "This subtask and milestones are resonable and could be successfully achieved. You can take this subtask as reference."
        elif "submit_result" in subtask:
            sub_plan["suggestion"] = subtask["submit_result"]["args"]["suggestions_for_latter_subtasks_plan"]["reason"]
        sub_plans.append(sub_plan)
    # Add the subplans finally as reference
    ref_plan["subtasks"] = sub_plans

    return json.dumps(ref_plan, indent=2, ensure_ascii=False)


def get_additional_msg_from_retrieve(now_dealing_task: Plan, ultimate_goal):
    # Need to choose from here whether current level goal or a upper level goal is wanted
    cur_level_goal = now_dealing_task.data.goal
    father_level_goal = now_dealing_task.father.data.goal
    cur_ref_plan = refine_db_retrieve_to_reference(cur_level_goal)
    father_ref_plan = refine_db_retrieve_to_reference(father_level_goal)
    
    # Get the submit results, it should be a FAILED task
    fail_conclusion = now_dealing_task.to_json()["submit_result"]["args"]["result"]["conclusion"]
    suggestion = now_dealing_task.to_json()["submit_result"]["args"]["suggestions_for_latter_subtasks_plan"]["reason"]
    fail_task_id = now_dealing_task.to_json()["task_id"]
    fail_task_name = now_dealing_task.to_json()["name"]
    fail_task_goal = now_dealing_task.to_json()["goal"]
            
    summary = json.dumps({"fail_task_id": fail_task_id, "fail_task_name": fail_task_name, "fail_task_goal": fail_task_goal, "conclusion": fail_conclusion, "suggestion_for_refine": suggestion}, indent=2, ensure_ascii=False)
            
    goals = json.dumps({"current_goal(just failed)": cur_level_goal, "parent_goal(local goal)": father_level_goal, "ultimate_goal": ultimate_goal}, indent=2, ensure_ascii=False)
            
    additional_message = Message("user", f"You have just failed the task {fail_task_id}. I have summarized the failed task and corresponding suggestions for you:\n{summary}\nI have also summarized the goals for you:\n{goals}\nTo successfully achieve the ultimate goal, you now need to refine your local plan.\n\n--- Reference Plans ---\nI will now give you some reference from database to help you make plan refinement.\n1. The following reference task's goal is similar to your current goal. You can refer to this task's plan to help the refinement if you still want to tackle the current goal by through SPLIT:\n{cur_ref_plan}\n2. The following reference task's goal is similar to your parent's goal. You can refer to this task's plan to help the refinement if you still want to jump out of current goal and tackle the parent's goal in a new way through ADD and DELETE:\n{father_ref_plan}\n\n--- Refinement Suggestions ---\nThere are typically two ways to tackle a failed situation\n1. If you think the current goal is very important and must be done in order to successfully complete the parent's goal and the ultimate goal, then you can SPLIT the current task {fail_task_id} into multiple subtasks and handle them again.\n2. If you think you have fallen to a dead end and the current goal is unreachable, you can ADD subtask and input the target task id {fail_task_id}, which will make your plan inserted as {str(fail_task_id)[:-1]+str(int(fail_task_id[-1])+1)}, and then DELETE some later subtasks that you think are unnecessary. This choice indicates you want to try a brand new way to solve the parent's goal, instead of focusing on the current task.\n\nAlways remember your ultimate goal. Please also refer to the plans if they are useful or inspirational. When refining the plan, avoid devising subtasks that are likely to FAIL, observe what subtasks are more likely to SUCCESS, and learn from suggestions.")

    return additional_message


class PlanRefineChain():
    def __init__(self, init_plan):
        self.plans = [deepcopy(init_plan)]
        self.functions = []
    
    def register(self,function_name, function_input,function_output,new_plan: Plan):
        self.functions.append({
            "name": function_name,
            "input": function_input,
            "output": function_output,
        })
        self.plans.append(deepcopy(new_plan))

        recorder.regist_plan_modify(
            refine_function_name = function_name,
            refine_function_input = function_input,
            refine_function_output = function_output,
            plan_after = new_plan.to_json(posterior=True),
        )
    
    def parse_to_message_list(self, flag_changed) -> List[Message]:
        assert len(self.plans) == len(self.functions) + 1
        
        if CONFIG.enable_summary: 
            init_message = summarize_plan(self.plans[0].to_json())
        else:
            init_message = json.dumps(self.plans[0].to_json(),indent=2,ensure_ascii=False)
        init_message =  Message("user", f"""The initial plan and the execution status is:\n'''\n{init_message}\n'''\n\n""")
        output_list = [init_message]
        for k, (function, output_plan) in enumerate(zip(self.functions, self.plans[1:])):
            operation_message = Message("user", f"""For the {k+1}\'th step, You made the following operation:
function_name: {function["name"]}
'''
{json.dumps(function["input"],indent=2,ensure_ascii=False)}
'''

Then get the operation result:
{function["output"]}

""")
            output_list.append(operation_message)
        if len(self.plans) > 1:
            if flag_changed:
                if CONFIG.enable_summary: 
                    new_message = summarize_plan(self.plans[-1].to_json())
                else:
                    new_message = json.dumps(self.plans[-1].to_json(),indent=2,ensure_ascii=False)
                output_list.append(Message("user", f"""The total plan changed to follows:\n'''\n{new_message}\n'''\n\n"""))
            else:
                output_list.append(Message("user", f"The total plan stay unchanged"))
        return output_list

class PlanAgent():
    def __init__(self, config, query: BaseQuery, avaliable_tools_description_list: List[dict]):
        self.config = config
        self.query = query
        self.avaliable_tools_description_list = avaliable_tools_description_list

        self.plan = Plan(
            data = TaskSaveItem(
                name=f"act as {query.role_name}",
                goal=query.task,
                milestones=query.plan,
                # tool_budget=100,
            )
        )

        self.refine_chains: List[PlanRefineChain] = []


    def initial_plan_generation(self, init_plan):
        if init_plan == None:
            logger.typewriter_log(
                f"-=-=-=-=-=-=-= GENERATE INITIAL_PLAN -=-=-=-=-=-=-=",
                Fore.GREEN,
                "",
            )
        else:
            logger.typewriter_log(
            f"-=-=-=-=-=-=-= INITIAL_PLAN AlREADY GIVEN IN YAML-=-=-=-=-=-=-=",
            Fore.GREEN,
            "",
        )
        
        # If there's initial plan given by the user
        if init_plan != None and "subtasks" in init_plan:
            subtasks = init_plan["subtasks"]
            # Add a switch, register like this if there's no evolve
            if not self.config.enable_self_evolve:
                for subtask_item in subtasks:
                    subplan = plan_function_output_parser(subtask_item)
                    Plan.make_relation(self.plan, subplan)
            return subtasks


        split_functions = deepcopy(function_manager.get_function_schema('subtask_split_operation'))
        # split_functions["parameters"]["properties"]["subtasks"]["items"]["properties"]["expected_tools"]["items"]["properties"]["tool_name"]["enum"] = [cont["name"] for cont in self.avaliable_tools_description_list]

        agent = agent_dispatcher.dispatch(
            RequiredAbilities.plan_generation,
            target_task=f"Generate a plan to accomplish the task: {self.query.task}",
            # avaliable_tools_description_list=self.avaliable_tools_description_list
        )

        # TODO: not robust. dispatcher generated prompt may not contain these specified placeholders?
        _, new_message , _ = agent.parse(
            placeholders={
                "system": {
                    # "avaliable_tool_descriptions": json.dumps(self.avaliable_tools_description_list, indent=2, ensure_ascii=False),
                    "avaliable_tool_names": str([cont["name"] for cont in self.avaliable_tools_description_list]),
                },
                "user": {
                    "query": self.plan.data.raw
                }
            },
            functions=[split_functions], 
            function_call={"name":"subtask_split_operation"},
        )
        
        subtasks = json5.loads(new_message["function_call"]["arguments"])

        # Add a switch, register like this if there's no evolve
        if not self.config.enable_self_evolve:
            for subtask_item in subtasks["subtasks"]:
                subplan = plan_function_output_parser(subtask_item)
                Plan.make_relation(self.plan, subplan)
        
        return subtasks

    def plan_iterate_based_on_memory_system(self, initial_subtasks):
        # Prepare the format of previous 
        subtask_cnt = 1
        for subtask in initial_subtasks["subtasks"]:
            subtask["task_id"] = f"1.{subtask_cnt}"
            subtask_cnt += 1
        previous_plan = {"query": self.query.task, "thought": initial_subtasks["thought"], 'target_subtask_id': "1", 'subtasks': initial_subtasks['subtasks']}
        previous_plan = json.dumps(previous_plan, indent=2, ensure_ascii=False)
        logger.typewriter_log(
            f"-=-=-=-=-=-=-= REFINE PLAN BASED ON MEMORY SYSTEM -=-=-=-=-=-=-=",
            Fore.BLUE,
        )
        
        split_functions = deepcopy(function_manager.get_function_schema('subtask_split_operation'))
        
        agent = agent_dispatcher.dispatch(
            RequiredAbilities.plan_interact_db,
            target_task=f"Generate a plan to accomplish the task: {self.query.task}", # useless when enable=False
        )
        
        ref_plan = change_db_retrieve_to_reference(self.query.task)
        
        # Retrieve from the database
        _, new_message , _ = agent.parse(
            placeholders={
                "system": {
                    "db_plans": ref_plan,
                    "previous_plan": previous_plan
                },
                "user": {
                    "query": self.plan.data.raw
                }
            },
            functions=[split_functions], 
            function_call={"name":"subtask_split_operation"},
        )
        
        subtasks = json5.loads(new_message["function_call"]["arguments"])

        for subtask_item in subtasks["subtasks"]:
            subplan = plan_function_output_parser(subtask_item)
            Plan.make_relation(self.plan, subplan)
    

    @property
    def latest_plan(self):
        return self.plan

    def plan_refine_mode(self, now_dealing_task: Plan):
        # We should only refine plan when the current task fails! (we disregard the max_tool_call situation)
        assert now_dealing_task.to_json()['exceute_status'] == "FAIL"
        
        logger.typewriter_log(
            f"-=-=-=-=-=-=-= ITERATIVELY REFINE PLAN BASED ON TASK AGENT SUGGESTIONS -=-=-=-=-=-=-=",
            Fore.BLUE,
        )

        if not self.config.enable_self_evolve:
            self.refine_chains.append(PlanRefineChain(self.plan))
        else:
            # Prompt里保留当前task父节点下的所有孩子的这样一颗子树
            self.refine_chains.append(PlanRefineChain(now_dealing_task.father))

        modify_steps = 0
        max_step = self.config.max_plan_refine_chain_length

        agent = agent_dispatcher.dispatch(
            RequiredAbilities.plan_refinement, 
            target_task="Refine the given plan.", 
            # avaliable_tools_description_list=self.avaliable_tools_description_list
        )
        try:
            refine_node_message = now_dealing_task.process_node.data["command"]["properties"]["args"]
            refine_node_message = refine_node_message["suggestions_for_latter_subtasks_plan"]["reason"]
        except:
            refine_node_message = ""
        workspace_files = str(toolserver_interface.execute_command_client("FileSystemEnv_print_filesys_struture", {"return_root":True}))
        
        while modify_steps < max_step:

            logger.typewriter_log(
                f"-=-=-=-=-=-=-= Continually refining planning (still in the loop)-=-=-=-=-=-=-=",
                Fore.GREEN,
            )

            subtask_id = now_dealing_task.get_subtask_id(to_str=True)
            flag_changed = False
            
            additional_message_list = self.refine_chains[-1].parse_to_message_list(flag_changed)

            function_call = None
            functions=[deepcopy(function_manager.get_function_schema('subtask_operations'))]
            function_call = {"name":"subtask_operations"}
            # print(message_list)
            try_times = 0

            if self.config.enable_self_evolve:
                # Get the additional message by retrieving from DB
                new_additional_message = get_additional_msg_from_retrieve(now_dealing_task, self.plan.data.goal)
                additional_message_list.append(new_additional_message)
            
            while True:
                _,new_message , _ = agent.parse(
                    placeholders={
                        "system": {
                            # "avaliable_tool_descriptions": json.dumps(self.avaliable_tools_description_list, indent=2, ensure_ascii=False),
                            "avaliable_tool_names": str([cont["name"] for cont in self.avaliable_tools_description_list]),
                            "max_plan_tree_width": self.config.max_plan_tree_width,
                            "max_plan_tree_depth": self.config.max_plan_tree_depth,
                        },
                        "user": {
                            "subtask_id": subtask_id,
                            "max_step": max_step,
                            "modify_steps": modify_steps,
                            "max_plan_tree_depth": self.config.max_plan_tree_depth,
                            "workspace_files": workspace_files[:1000],
                            "refine_node_message":refine_node_message,
                        }
                    }, 
                    functions=functions, 
                    function_call=function_call,
                    additional_messages=additional_message_list,
                    additional_insert_index=-1,
                    restrict_cache_query = (try_times > 0),
                )
                # print(new_message)
                if not "function_call" in new_message.keys():
                    print("function_call not found, continue to call the LLM API for a new function_call")
                    try_times += 1
                    continue
                function_name = new_message["function_call"]["name"]
                function_input = json5.loads(new_message["function_call"]["arguments"])
                break

            if function_input['operation'] == 'split':
                # modify function_input here
                function_output, output_status_code = self.deal_subtask_split(function_input, now_dealing_task)
            elif function_input['operation'] == 'add':
                function_output, output_status_code = self.deal_subtask_add(function_input, now_dealing_task)
            elif function_input['operation'] == 'delete':
                function_output, output_status_code = self.deal_subtask_delete(function_input, now_dealing_task)
            elif function_input['operation'] == 'exit':
                output_status_code = PlanOperationStatusCode.PLAN_REFINE_EXIT
                function_output = json.dumps({
                    "content": "exit PLAN_REFINE_MODE successfully",
                })
            else:
                logger.typewriter_log("Error: ", Fore.RED, f"Operation {function_input['operation']} not found. Nothing happens")
                output_status_code = PlanOperationStatusCode.PLAN_OPERATION_NOT_FOUND
                function_output = json.dumps({
                    "error": f"Operation {function_input['operation']} not found. Nothing happens"
                })
            
            if "error" not in function_output:
                flag_changed = True
            
            self.refine_chains[-1].register(function_name=function_name,
                                            function_input=function_input,
                                            function_output=function_output,
                                            # If in refine modify mode, only the father task will be modified
                                            new_plan=now_dealing_task.father if self.config.enable_self_evolve else self.plan)

            if output_status_code == PlanOperationStatusCode.MODIFY_SUCCESS:
                color = Fore.GREEN
            elif output_status_code == PlanOperationStatusCode.PLAN_REFINE_EXIT:
                color = Fore.YELLOW
            else:
                color = Fore.RED
            logger.typewriter_log("SYSTEM: ", Fore.YELLOW, function_output)
            logger.typewriter_log(
                "PLAN MODIFY STATUS CODE: ", Fore.YELLOW, f"{color}{output_status_code.name}{Style.RESET_ALL}"
            )

            if output_status_code == PlanOperationStatusCode.PLAN_REFINE_EXIT or output_status_code == PlanOperationStatusCode.MODIFY_SUCCESS:
                return

            modify_steps += 1

    def deal_subtask_split(self, function_input: dict, now_dealing_task: Plan) -> (str, PlanOperationStatusCode):
        print(json.dumps(function_input,indent=2,ensure_ascii=False))

        inorder_subtask_stack = Plan.get_inorder_travel(self.plan)
        target_subtask_id = function_input["target_subtask_id"].strip()
        all_subtask_ids = [cont.get_subtask_id(to_str=True) for cont in inorder_subtask_stack]

        can_edit = False
        for k, subtask in enumerate(inorder_subtask_stack):
            if subtask.get_subtask_id(to_str=True) == now_dealing_task.get_subtask_id(to_str=True):
                
                can_edit = True

            if subtask.get_subtask_id(to_str=True) == target_subtask_id:
                if not can_edit:
                    return json.dumps({"error": f"You can only split the TODO subtask plans together with the now_dealing_subtask, e.g. '>= {now_dealing_task.get_subtask_id(to_str=True)}'. Nothing happended",}), PlanOperationStatusCode.MODIFY_FORMER_PLAN
                
                # if not subtask.data.status == TaskStatusCode.FAIL:
                #     return json.dumps({"error": f"You can only split the FAIL subtask plans together. This is a '{subtask.data.status.name}' Task. Nothing happended"}), PlanOperationStatusCode.OTHER_ERROR

                if subtask.get_depth() >= self.config.max_plan_tree_depth:
                    return json.dumps({"error": f"The plan tree has a max depth of {self.config.max_plan_tree_depth}. '{subtask.data.name}' already has a depth of {subtask.get_depth()}. Nothing happended"}), PlanOperationStatusCode.OTHER_ERROR

                for new_subtask in function_input["subtasks"]:
                    new_subplan = plan_function_output_parser(new_subtask)
                    Plan.make_relation(subtask,new_subplan)
                subtask.data.status = TaskStatusCode.SPLIT
                return json.dumps({"success": f"Subtask '{target_subtask_id}' has been split",}), PlanOperationStatusCode.MODIFY_SUCCESS

        return json.dumps({"error": f"target_subtask_id '{target_subtask_id}' not found. Nothing happended",}), PlanOperationStatusCode.TARGET_SUBTASK_NOT_FOUND


    def deal_subtask_delete(self, function_input: dict, now_dealing_task: Plan) -> (str, PlanOperationStatusCode):
        print(json.dumps(function_input,indent=2,ensure_ascii=False))

        inorder_subtask_stack:list[Plan] = Plan.get_inorder_travel(self.plan)
        target_subtask_id = function_input["target_subtask_id"].strip()

        all_subtask_ids = [cont.get_subtask_id(to_str=True) for cont in inorder_subtask_stack]

        can_edit = False
        for k, subtask in enumerate(inorder_subtask_stack):
            if subtask.get_subtask_id(to_str=True) == target_subtask_id:
                if not can_edit:
                    return json.dumps({"error": f"You can only delete the TODO subtask plans, e.g., task_id>'{now_dealing_task.get_subtask_id(to_str=True)}', you are deleting {subtask.get_subtask_id(to_str=True)}. Nothing happended"}), PlanOperationStatusCode.MODIFY_FORMER_PLAN
                
                
                if subtask.data.status != TaskStatusCode.TODO :
                    return json.dumps({"error": f"You can only delete the TODO subtask plans, e.g., task_id>'{now_dealing_task.get_subtask_id(to_str=True)}', you are deleting {subtask.get_subtask_id(to_str=True)}. Nothing happended"}), PlanOperationStatusCode.MODIFY_FORMER_PLAN
                
                # try to delete the subtask
                subtask.father.children.remove(subtask)
                subtask.father = None
                
                return json.dumps({"success": f"Subtask '{target_subtask_id}' has been deleted",}), PlanOperationStatusCode.MODIFY_SUCCESS
            if subtask.get_subtask_id(to_str=True) == now_dealing_task.get_subtask_id(to_str=True):
                
                can_edit = True

        return json.dumps({"error": f"target_subtask_id '{target_subtask_id}' not found, should in {all_subtask_ids}. Nothing happended",}), PlanOperationStatusCode.TARGET_SUBTASK_NOT_FOUND


    def deal_subtask_modify(self, function_input: dict, now_dealing_task: Plan) -> (str, PlanOperationStatusCode):
        print(json.dumps(function_input,indent=2,ensure_ascii=False))

        inorder_subtask_stack = Plan.get_inorder_travel(self.plan)
        target_subtask_id = function_input["target_subtask_id"].strip()

        all_subtask_ids = [cont.get_subtask_id(to_str=True) for cont in inorder_subtask_stack]

        can_edit = False
        for k, subtask in enumerate(inorder_subtask_stack):
            if subtask.get_subtask_id(to_str=True) == target_subtask_id:
                if not can_edit:
                    return json.dumps({"error": f"You can only modify the TODO subtask plans, e.g., task_id>'{now_dealing_task.get_subtask_id(to_str=True)}', you are modifying {subtask.get_subtask_id(to_str=True)}. Nothing happended"}), PlanOperationStatusCode.MODIFY_FORMER_PLAN
                
                assert subtask.data.status == TaskStatusCode.TODO
                subtask.data.load_from_json(function_input["new_data"])

                return json.dumps({"success": f"Subtask '{target_subtask_id}' has been modified",}), PlanOperationStatusCode.MODIFY_SUCCESS
            if subtask.get_subtask_id(to_str=True) == now_dealing_task.get_subtask_id(to_str=True):
                
                can_edit = True

        return json.dumps({"error": f"target_subtask_id '{target_subtask_id}' not found, should in {all_subtask_ids}. Nothing happended",}), PlanOperationStatusCode.TARGET_SUBTASK_NOT_FOUND

    def deal_subtask_add(self, function_input: dict, now_dealing_task: Plan) -> (str, PlanOperationStatusCode):
        print(json.dumps(function_input,indent=2,ensure_ascii=False))

        inorder_subtask_stack:list[Plan] = Plan.get_inorder_travel(self.plan)
        former_subtask_id = function_input["target_subtask_id"].strip()

        all_subtask_ids = [cont.get_subtask_id(to_str=True) for cont in inorder_subtask_stack]

        # check whether the former_subtask_id is valid

        former_subtask = None
        for subtask in inorder_subtask_stack:
            if subtask.get_subtask_id(to_str=True) == former_subtask_id:
                former_subtask = subtask
                break
        if former_subtask is None:
            return json.dumps({"error": f"former_subtask_id '{former_subtask_id}' not found, should in {all_subtask_ids}. Nothing happended",}), PlanOperationStatusCode.TARGET_SUBTASK_NOT_FOUND
        
        former_subtask_id_list = former_subtask.get_subtask_id_list()
        now_dealing_task_id_list = now_dealing_task.get_subtask_id_list()
        
        if int(former_subtask_id_list[-1]) + len(function_input["subtasks"]) > self.config.max_plan_tree_width:
            return json.dumps({"error": f"The plan tree has a max width of {self.config.max_plan_tree_width}. '{former_subtask.data.name}' already has a width of {len(former_subtask.children)}. Nothing happended"}), PlanOperationStatusCode.OTHER_ERROR
            
        for i in range(min(len(former_subtask_id_list), len(now_dealing_task_id_list))):
            if former_subtask_id_list[i]<now_dealing_task_id_list[i]:
                return json.dumps({"error": f"You can only add the subtask plans after than now_dealing task, e.g. 'former_subtask_id >= {now_dealing_task.get_subtask_id(to_str=True)}'. Nothing happended",}), PlanOperationStatusCode.MODIFY_FORMER_PLAN
        # pass check
        new_subplans = [plan_function_output_parser(new_subtask) for new_subtask in function_input["subtasks"]]

        subtask = former_subtask
        if subtask.father is None:
            return json.dumps({"error":f"Currently not support adding a subtask at root level!"}), PlanOperationStatusCode.MODIFY_FORMER_PLAN
        # assert subtask.father != None
        index = subtask.father.children.index(subtask)

        for new_subplan in new_subplans:
            new_subplan.father = subtask.father
        subtask.father.children[index+1:index+1] = new_subplans
        
        return json.dumps({"success": f"A new subtask has been added after '{former_subtask_id}'",}), PlanOperationStatusCode.MODIFY_SUCCESS