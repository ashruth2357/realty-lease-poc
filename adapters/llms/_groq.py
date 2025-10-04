import os

from groq import Groq


chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "Explain the importance of fast language models",
        }
    ],
    model="llama-3.3-70b-versatile",
)

print(chat_completion.choices[0].message.content)

from typing import List
from adapters.llms.base import LargeLanguageModel 
from openai import OpenAI
from utils.schemas import LeaseDocument
import json 

with open("/Users/vivek.singh/realty-poc/utils/references/lease_abstraction.json", 'r') as file:
    reference = json.load(file)


class _Groq(LargeLanguageModel):
    def __init__(self, model_name: str = "gpt-5"):
        self.client = Groq(
            # This is the default and can be omitted
            api_key=os.environ.get("GROQ_API_KEY"),
        )
        self.model_name = "openai/gpt-oss-120b"
        
    def get_streaming_response(self, payload: List[dict]):
        return self.client.chat.completions.create(
                model=self.model_name,
                messages=payload,
                stream=True,
                temperature = 0,
            ) 
    
    def get_non_streaming_response(self, payload: List[dict]):
        return self.client.chat.completions.create(
                messages=payload,
                model=self.model_name,
            )