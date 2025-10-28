import streamlit as st

st.title("👋 Hello Streamlit!")
st.write("If you can see this, Streamlit is working correctly.")

name = st.text_input("What's your name?")
if name:
    st.success(f"Hello, {name}!")
