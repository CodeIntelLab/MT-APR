import platform
import torch
#from transformers import AutoModelForCausalLM, AutoTokenizer, TextStreamer

class LocalChat:
    def __init__(self, dir, model, proxy):
        self.model_dir = dir
        self.model_name = model
        self.proxy = proxy

        self.model_path = self.model_name if self.model_dir == 'default' else self.model_dir
        self.device = self.detect_device()
        print(f"Using device: {self.device}")

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype=torch.float16,
            device_map='auto',
            low_cpu_mem_usage=True
        )

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            padding_side="left",
            use_fast=False
        )

        self.streamer = TextStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True
        )

    def detect_device(self):
        import platform
        os_name = platform.system().lower()
        if os_name == 'darwin' and torch.backends.mps.is_available():
            return torch.device("mps")
        elif torch.cuda.is_available():
            return torch.device("cuda")
        else:
            return torch.device("cpu")

    def encode(self, text):
        return self.tokenizer(text, return_tensors="pt", add_special_tokens=False).input_ids.to(self.device)

    def generate(self, input_ids, streamer=None, temperature=0.0):
        return self.model.generate(
            input_ids,
            streamer=streamer,
            max_new_tokens=8192,
            do_sample=True,
            top_k=30,
            top_p=0.85,
            temperature=temperature,
            repetition_penalty=1.0,
            pad_token_id=self.tokenizer.eos_token_id
        )

    def decode(self, output_ids):
        decoded = self.tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0]
        # 如果有 [/INST]，只取最后一段，否则取全部
        if '[/INST]' in decoded:
            response = decoded.split('[/INST]')[-1].strip()
        else:
            response = decoded.strip()
        return response

    def chat(self, prompt, ID, temperature=0.0):
        try:
            with torch.no_grad():
                # 初始化 prompt
                input_ids = self.encode('<s>')
                for msg in prompt:
                    if msg['role'] == 'user':
                        input_ids = torch.cat([
                            input_ids,
                            self.encode("[INST]"),
                            self.encode(msg['content'].strip()),
                            self.encode("[/INST]")
                        ], dim=-1)
                    else:
                        input_ids = torch.cat([
                            input_ids,
                            self.encode(msg['content'].strip()),
                            self.encode('</s>')
                        ], dim=-1)

                # 生成 output
                if self.proxy == 'stream':
                    output_ids = self.generate(input_ids, self.streamer, temperature)
                elif self.proxy == 'batch':
                    output_ids = self.generate(input_ids, None, temperature)
                else:
                    raise ValueError("Proxy must be 'stream' or 'batch'")

                response = self.decode(output_ids)

                # Debug 打印
                if not response:
                    print(f"ID: {ID} - Warning: model returned empty response")
                else:
                    print(f"ID: {ID} - Successfully generated response, length={len(response)}")

            return response

        except Exception as e:
            print(f"ID: {ID} - Exception during chat: {str(e)}")
            return ""
