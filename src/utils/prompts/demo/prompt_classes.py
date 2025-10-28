from pydantic import BaseModel

class Demo1BM(BaseModel):
    restate: str
    brainstorm: str

class Demo2BM(BaseModel):
    cadidate1: str
    cadidate2: str
    cadidate3: str
    final_answer: str
