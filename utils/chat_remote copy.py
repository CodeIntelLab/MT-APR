import requests
import time
from retry import retry

class RemoteChat:
    def __init__(self, api_key, model, proxy):
        self.api_key = api_key
        self.model = model
        self.proxy = proxy

    @retry(tries=3, delay=2, backoff=2)
    def safe_request(self, url, data, headers):
        response = requests.post(url, json=data, headers=headers)
        return response.json()

    def chat(self, prompt, ID, temperature=0.0):
        data = {
            'model': self.model,
            'messages': prompt,
            'temperature': temperature
        }

        # 根据 proxy 类型选择不同平台
        if self.proxy == 'AI':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            url = 'https://api.ai-gaochao.cn/v1/chat/completions'
        elif self.proxy == 'OMG':
            headers = {
                'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            url = 'https://aigptx.top/v1/chat/completions'
        elif self.proxy == 'OpenAI':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            url = 'https://api.openai.com/v1/chat/completions'
        elif self.proxy == 'B3N':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            url = 'https://api.b3n.fun/v1/chat/completions'
        elif self.proxy == 'DeepSeek':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            url = 'https://api.deepseek.com/v1/chat/completions'
        elif self.proxy == 'YUNWU':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            url = 'https://yunwu.ai/v1/chat/completions'
        else:
            raise ValueError("proxy must be 'AI', 'OMG', 'OpenAI', 'B3N', 'DeepSeek', or 'YUNWU'")

        # 尝试请求，最多 10 次
        ti = 0
        response = None
        usage = None
        while ti <= 10:
            print(">>> BEFORE REQUEST POST", flush=True)
            response_api = self.safe_request(url, data, headers)
            print(">>> AFTER REQUEST POST", flush=True)
            try:
                response = response_api['choices'][0]['message']['content']
                usage = response_api.get('usage', None)  # ⭐ 获取 token 使用信息
                print(f"ID: {ID}:\tSuccessfully made request")
                break
            except Exception as e:
                print(f"ID: {ID}:\tRequest failed: {response_api}")
                ti += 1
                time.sleep(3)

        # 返回内容和 usage
        return response, usage
