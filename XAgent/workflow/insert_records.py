import os
import json
from IPython import embed
from XAgent.vector_db import VectorDBInterface
from XAgent.global_vars import vector_db_interface as vecdb


def update_subdict(ori_dict, id, update_items):
    for cur_dict in ori_dict:
        if cur_dict["task_id"] == id:
            for k, v in update_items.items():
                cur_dict[k] = v
            return ori_dict, True
        if "subtask" in cur_dict.keys():
            _, success = update_subdict(cur_dict["subtask"], id, update_items)
            if success:
                return ori_dict, True
    return ori_dict, False


def dict_insert_vec(ori_dict):
    for cur_dict in ori_dict:
        goal = cur_dict["goal"]
        status = cur_dict["exceute_status"]
        insert_dict = {
            "goal": cur_dict["goal"],
            "prior_plan_criticsim": cur_dict["prior_plan_criticsim"],
            "milestones": cur_dict["milestones"],
            "if_success_previously": status if (status == "SUCCESS" or status == "FAIL") else "UNKNOWN",
            "action_list_summary": "UNAVAILABLE",
        }
        try:
            print("Valid summary presented!")
            insert_dict["action_list_summary"] = cur_dict["action_list_summary"]
        except:
            print("Summary unavailable currently")
        vecdb.insert_sentence(goal, json.dumps(insert_dict), "single_step_plan")
        if "subtask" in cur_dict.keys():
            dict_insert_vec(cur_dict["subtask"])
            

def workflow_insert_vec(ori_dict):
    insert_num = 0
    for cur_dict in ori_dict:
        if "subtask" not in cur_dict:
            continue
        if "goal" not in cur_dict:
            continue
        # We insert all the workflow (subtree with leaves, we do not record lead node here)
        vecdb.insert_sentence(cur_dict["goal"].strip(), json.dumps(cur_dict, indent=2, ensure_ascii=False), "workflow")
        insert_num += 1
        insert_num += workflow_insert_vec(cur_dict["subtask"])
    return insert_num


def pop_tool_call_process(ori_dict):
    if "tool_call_process" in ori_dict.keys():
        del ori_dict["tool_call_process"]
    if "subtask" in ori_dict.keys():
        for subtask in ori_dict["subtask"]:
            pop_tool_call_process(subtask)
    return ori_dict


def post_process_plan_insert(plan):
    # Sometimes the plan is too long that the token exceeded. Need to pop out all the tool calls first.
    plan = pop_tool_call_process(plan)
    
    # Begin to insert the whole work flow as record in VecDB
    name = plan["name"].strip() + "\n"
    query = plan["goal"]
    vecdb.insert_sentence(name + query, json.dumps(plan, indent=2, ensure_ascii=False), "whole_workflow")
    print("Success insertion of whole plan into DB!")
    
    # # Begin to insert the single step plans as record in VecDB
    # if "subtask" in plan.keys():
    #     dict_insert_vec(plan["subtask"])

    # Begin to insert all the subtrees into the database (exclude all the leaves)
    total_insert = workflow_insert_vec([plan])
    print("Total worflow inserted:", total_insert)


if __name__ == "__main__":
    # insert all the records to the VectorDB accordingly
    path = "PATH_TO_RECORD"
    dirs = [0] # os.listdir(path)
    for dir in dirs:
        # Get the query
        try:
            query = json.load(open(os.path.join(path, dir, "query.json"), "r"))["task"]
        except:
            print(f"Cannot retrieve the query! Skip record {dir}")
            continue

        # Find if there is plan as cache
        if "plan.json" in os.listdir(os.path.join(path, dir)):
            print(f"Plan already exists for {dir}! Directly load from disk")
            plan = json.load(open(os.path.join(path, dir, "plan.json"), "r"))
        # Cache miss, construct the plan from the beginning
        else:
            # Get all the plan dirs in order
            subplan_dirs = os.listdir(os.path.join(path, dir))
            new_subplan_dirs = []
            for subplan_dir in subplan_dirs:
                if os.path.isdir(os.path.join(path, dir, subplan_dir)) and \
                    subplan_dir != "LLM_inout_pair" and subplan_dir != "tool_server_pair":
                    new_subplan_dirs.append(subplan_dir)
            subplan_dirs = sorted(new_subplan_dirs)[::-1]
            
            # # Get the final plan of the model through "refine"
            # refine_exists = False
            # for subplan_dir in subplan_dirs:
            #     all_files = os.listdir(os.path.join(path, dir, subplan_dir))
            #     refine_files = []
            #     for file in all_files:
            #         if "plan_refine" in file:
            #             refine_files.append(file)
            #     if refine_files == []:
            #         continue
            #     refine_exists = True
            #     last_refine_file = sorted(refine_files)[-1]
            #     # get the final plan from the json file with "refine"
            #     plan = json.load(open(os.path.join(path, dir, subplan_dir, last_refine_file), "r"))["plan_after"]
            #     break
            
            # if not refine_exists:
            #     init_plan = json.load(open(os.path.join(path, dir, "LLM_inout_pair", "00000.json"), "r"))
            #     plan = eval(init_plan["output"]["choices"][0]["message"]["function_call"]["arguments"])
                
            # More efficient way: Get the plan directly through the last posterior knowledge
            LLM_inout_files = sorted(os.listdir(os.path.join(path, dir, "LLM_inout_pair")))[::-1]
            posterior_success = False
            for LLM_inout_file in LLM_inout_files:
                all_data = json.load(open(os.path.join(path, dir, "LLM_inout_pair", LLM_inout_file), "r"))
                content:str = all_data["input"]["messages"][0]["content"]
                if not content.startswith("You are posterior_knowledge_obtainer."):
                    continue
                posterior_success = True
                plan = content.split('BEGIN_ALL_PLAN\n"""\n')[1].split('\n"""\nEND_ALL_PLAN')[0]
                # eval(plan.replace(": false", ": False").replace(": true", ": True"))
                plan = json.loads(plan)
                break
            # Obviously it is not contact, jump to nect record
            if not posterior_success:
                print(f"No posterior found, progress incontact! Skip record {dir}")
                continue
            
            # Patch the last action summary to get the whole plan
            last_handled_plan = content.split('BEGIN_SUBTASK_PLAN\n"""\n')[1].split('\n"""\nEND_SUBTASK_PLAN')[0]
            # eval(last_handled_plan.replace(": false", ": False").replace(": true", ": True"))
            last_handled_plan = json.loads(last_handled_plan)
            last_handled_id = last_handled_plan['task_id']
            
            LLM_response = eval(all_data["output"]["choices"][0]["message"]["function_call"]["arguments"])
            # Note: the plan is passed in as List (to align with the subtask as list, convenient for )
            plan, success = update_subdict([plan], last_handled_id, {"action_list_summary": LLM_response["summary"]})
            plan = plan[0]
            if not success:
                print(f"Cannot find task id {last_handled_id} in plan! Skip record {dir}")
                continue
            
            for subplan_dir in subplan_dirs:
                tool_call_files = sorted(os.listdir(os.path.join(path, dir, subplan_dir)))
                all_calls = []
                for tool_call_file in tool_call_files:
                    if "plan_refine" in tool_call_file:
                        continue
                    tool_call = json.load(open(os.path.join(path, dir, subplan_dir, tool_call_file), "r"))
                    all_calls.append(tool_call)
                plan, success = update_subdict([plan], subplan_dir, {"tool_call_process": all_calls})
                plan = plan[0]
            
            open(os.path.join(path, dir, "plan.json"), "w").write(json.dumps(plan, indent=2, ensure_ascii=False))
        
        # Until now, the plan's hierarchy is like:
        # For each task (subtask):
        # - name, goal, prior_plan_criticsim, milestones, exceute_status, task_id
        # - subtask: [{...}, ...] a list of other subtasks, exist when status is SPLIT
        # (below are the additional items besides root node)
        # - action_list_summary: the summary of what this level of subtask has done
        # - submit_result: the submission of current level of task
        # - tool_call_process: the chain of tool calls and results (workflow of this subtask)

        post_process_plan_insert(plan)
