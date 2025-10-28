DECIDE_TO_RESPOND_TEMPERATURE = 0.5
RESPOND_TEMPERATURE = 0.9
STYLIZER_TEMPERATURE = 0.5

with open("./src/utils/prompts/v0/feedback.txt", "r") as f:
    FEEDBACK = f.read()