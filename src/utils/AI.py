'''
2025-10-28
Author: Dan Schumacher
How to run (For debugging):
   python ./src/utils/AI.py
'''
####################################################################################################
import sys; sys.path.append('./src/')  # to allow relative imports when running this file directly
import re
from typing import Dict, List, Union #, Tuple
from utils.prompter import Prompter, OpenAIPrompter
# from utils.states import PlayerState
from utils.constants import (
    DECIDE_TO_RESPOND_TEMPERATURE, RESPOND_TEMPERATURE, STYLIZER_TEMPERATURE, FEEDBACK)
####################################################################################################

class AIPlayer:
    '''blah'''
    def __init__(self, persona:dict, debug_bool:int=0) -> None:
        self.persona = persona
        self.debug_bool = debug_bool
        self.doppels_messages: list = persona.get("text_samples")

        self.prompter_dict: Dict[str, Prompter] = {
        "decide_to_respond": OpenAIPrompter(
            prompt_path="./src/utils/prompts/v0/decide_to_respond.yaml",
            prompt_headers={
                "persona": "HERE IS YOUR PERSONA",
                "minutes": "HERE IS THE CONVERSATION SO FAR",
            },
            show_prompt = self.debug_bool,
            temperature=DECIDE_TO_RESPOND_TEMPERATURE,
            llm_model="gpt-4.1-mini",
        ),
        "respond": OpenAIPrompter(
            prompt_path="./src/utils/prompts/v0/respond.yaml",
            prompt_headers={
                "feedback": "HERE IS FEEDBACK FROM PREVIOUS GAMES",
                "persona": "HERE IS YOUR PERSONA",
                "minutes": "HERE IS THE CONVERSATION SO FAR",
                "reasoning": "YOU HAVE DECIDED TO ANSWER FOR THE FOLLOWING REASONIG"
                },
            show_prompt = self.debug_bool,
            temperature=RESPOND_TEMPERATURE,
            llm_model="gpt-4.1-mini",
        ),
        "stylizer": OpenAIPrompter(
            prompt_path="./src/utils/prompts/v0/stylizer.yaml",
            prompt_headers={
                "player_minutes": "HERE ARE MESSAGES THAT YOU WILL COPY THE STYLE FROM",
                "message": "HERE IS THE MESSAGE YOU WILL STYLIZE",
            },
            show_prompt = self.debug_bool,
            temperature=STYLIZER_TEMPERATURE,
            llm_model="gpt-4.1-mini",
        )
    }
        

    @staticmethod
    def _extract_between_delimiters(text: str, delim: str) -> str:
        """
        Extracts the first occurrence of text between two identical delimiters.

        Args:
            text: The full string to search.
            delim: The delimiter used on both sides (e.g., '```').

        Returns:
            The text between the delimiters, or an error message if no match is found.
        """
        pattern = re.escape(delim) + r'(.*?)' + re.escape(delim)
        match = re.search(pattern, text, re.DOTALL)  # DOTALL handles multi-line blocks if needed
        return match.group(1).strip() if match else f"ERROR NO MATCH FOUND ||| DELIM = {delim} ||| TEXT = {text}"

    def add_doppel_messages(self, messages:Union[List[str], str]) -> None:
        '''blah'''
        if isinstance(messages, str):
            self.doppels_messages.append(messages)
        else:
            self.doppels_messages.extend(messages)
        
    def decide_to_respond(self, minutes:str) -> Dict[str, str]:
        '''blah'''
        # Prepare response container
        dtr_resp = {}

        prompter = self.prompter_dict["decide_to_respond"]
        response = prompter.get_completion({
            "persona": self.persona,
            "minutes": minutes,
            })
        decision = self._extract_between_delimiters(response, '```')
        reasoning = self._extract_between_delimiters(response, '***')

        
        # IF WE HAVE A VALID RESPONSE, RETURN IT 
        if "ERROR NO MATCH FOUND" not in decision and "ERROR NO MATCH FOUND" not in reasoning:

            dtr_resp["decision"] = decision
            dtr_resp["reasoning"] = reasoning
                                                                        # self.logger.info(f'DTR DECISION: {dtr_resp["decision"]}')
                                                                        # self.logger.info(f'DTR REASONING: {dtr_resp["reasoning"]}')

        else:
            dtr_resp["decision"] = "INVALID_FORMAT"
            dtr_resp["reasoning"] = "INVALID_FORMAT"
            # raise ValueError(f"Invalid format in decision response: {dtr_resp}")
                                                                        # self.logger.error(f'DTR DECISION: {dtr_resp["decision"]}')
                                                                        # self.logger.error(f'DTR REASONING: {dtr_resp["reasoning"]}')
        # print(dtr_resp)
        return dtr_resp


    def respond(self, reasoning:str, minutes:str) -> Dict[str, str]:
        '''blah'''
        prompter = self.prompter_dict["respond"]
        response = prompter.get_completion({
            "feedback": FEEDBACK,
            "persona": self.persona, 
            "minutes": "\n".join(minutes),
            "reasoning": reasoning
            })
        response = self._extract_between_delimiters(response, '```')
        return response
    


    def stylize_message(self,  message_to_stylize:str) -> str:
        '''blah'''
        prompter = self.prompter_dict["stylizer"]
        response = prompter.get_completion({
            "player_minutes": self.doppels_messages,
            "message": message_to_stylize
            })
        return response
    
    def full_chain_response(self, minutes:str, lst_of_human_msgs:list) -> str:
        '''blah'''
        dtr = self.decide_to_respond(minutes)
        if self.debug_bool:
            print(f"[AIPlayer] full_chain_response DTR: {dtr}")
        if dtr['decision'] =='RESPOND':
            generic_response = self.respond(dtr['reasoning'], minutes)
            if self.debug_bool:
                print(f"[AIPlayer] full_chain_response generic_response: {generic_response}")
            stylized_response = self.stylize_message(lst_of_human_msgs, generic_response)
            if self.debug_bool:
                print(f"[AIPlayer] full_chain_response stylized_response: {stylized_response}")
            return stylized_response
        else:
            return ""


####################################################################################################
if __name__ == "__main__":
    ai_paul = AIPlayer(
        persona={
            "name": "Paul", 
            "code_name": "EagleEye", 
            "text_samples": "I talk every opertunity I can\nRad yo!\nThats dope\n6767"
        }, 
        debug_bool=1
        )
    minutes = "Alice: Hi there!\nBob: Hello!"
    lst_of_human_paul_msgs = [
        "I'M PAUL AND I LIKE TO PARTY!",
        "LETS GET SWIGGGGYYY WITH IT",
        "TBH I MISS MY MOM"
    ]
    ai_paul.add_doppel_messages(lst_of_human_paul_msgs)
    response = ai_paul.full_chain_response(minutes, lst_of_human_paul_msgs)
####################################################################################################