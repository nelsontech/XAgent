import pinecone
import requests
import json
from XAgent.config import CONFIG, get_apiconfig_by_model

class VectorDBInterface():
    def __init__(self):
        # 初始化 Pinecone
        pinecone.init(api_key="XXX", environment="XXX")
        self.task_index = pinecone.Index("XXX")

        self.get_info()
        self.get_keys()
        
    def get_keys(self):
        self.turbo_keys = [get_apiconfig_by_model("gpt-3.5-turbo-16k")["api_key"]]
    #     self.turbo_keys = [] 
    #     lines = pool.split("\n")
    #     for line in lines:
    #         striped = line.strip()
    #         if striped == "":
    #             continue
    #         # contents = striped.split("|")
    #         # for cont in contents:
    #         #     if cont.startswith("sk-"):
    #         #         self.turbo_keys.append(cont)
    #         content = striped.split("----")[2].strip()
    #         if content.startswith("sk-"):
    #             self.turbo_keys.append(content)


    def get_info(self):
        # 定义函数：统计数据库信息
        try:
            info = self.task_index.describe_index_stats()
            self.vector_count = info["total_vector_count"]
            dimension = info['dimension']
            print(info)
            print("数据库维度: ", dimension)
            print("数据库向量数: ", self.vector_count)
        except:
            print("Warning:获取数据库信息失败")


    def generate_embedding(self, text:str):
        url = "https://api.openai.com/v1/embeddings"
        payload = {
            "model": "text-embedding-ada-002",
            "input": text
        }
        for key in self.turbo_keys:
            headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}"
            }
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            try:
                res = json.loads(response.text)
                embedding = res['data'][0]['embedding']
                return embedding
            except:
                pass

    def delete_sentence(self, sentence:str):
        # 定义函数：删除句子及其语义向量
        try:
            self.task_index.delete(sentence)
            print("删除句子成功: ", sentence)
        except:
            print("Warning:删除句子失败: ", sentence)

    def insert_sentence(self, vec_sentence:str, sentence:str, namespace=""):
        embedding = self.generate_embedding(vec_sentence)
        if embedding:
            try:
                self.task_index.upsert(
                    [(str(self.vector_count),
                    embedding,
                    {"text":sentence, "type":namespace})],
                    # namespace=namespace,
                )
                print("数据库插入成功")
                self.vector_count += 1
            except Exception as e:
                print(e)
                print("Warning:插入句子失败")
        else:
            print("Warning:生成语义向量失败")

    def search_similar_sentences(self, query_sentence:str, namespace="", top_k=1):
        # 定义函数：搜索相似句子
        embedding = self.generate_embedding(query_sentence)
        if embedding:
            try:
                res = self.task_index.query(
                    embedding,
                    top_k=top_k,
                    include_metadata=True,
                    include_values=False,
                    filter={
                        "type": {"$eq": namespace},
                    },
                )
                return res
            except Exception as e:
                print(e)
                print("Warning:搜索相似句子失败")
        else:
            print("Warning:生成语义向量失败: ")


if __name__ == "__main__":
    CONFIG.reload("../config.yml")
    VDB = VectorDBInterface()
    VDB.insert_sentence("I plan to go to cinema", "this is the tested meta data", "test1020")
    print(VDB.search_similar_sentences("hi, today is good", "test1020"))