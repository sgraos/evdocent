import streamlit as st
from snowflake.core import Root # requires snowflake>=0.8.0
#from snowflake.snowpark.context import get_active_session
#from access_creds import connection_params
from snowflake.snowpark import Session

@st.cache_resource
def create_session():
    return Session.builder.configs(st.secrets.snowflake).create()

MODELS = [
    "mistral-large"
]

def init_messages():
    if st.session_state.clear_conversation or "messages" not in st.session_state:
        st.session_state.messages = []

def init_service_metadata():
    if "service_metadata" not in st.session_state:
        service_metadata = [{"name":"REVIEW_SEARCH","search_column":"ARTICLE_TEXT"}]
        st.session_state.service_metadata = service_metadata

def init_config_options():
    st.sidebar.button("Clear conversation", key="clear_conversation")
    st.session_state['selected_cortex_search_service'] = "REVIEW_SEARCH"
    st.session_state['debug'] = False
    st.session_state['use_chat_history'] = True
    st.session_state['model_name'] = "mistral-large"
    st.session_state['num_retrieved_chunks'] = 5
    st.session_state['num_chat_messages'] = 3

def query_cortex_search_service(query):
    db, schema = session.get_current_database(), session.get_current_schema()

    cortex_search_service = (
        root.databases[db]
        .schemas[schema]
        .cortex_search_services[st.session_state.selected_cortex_search_service]
    )

    context_documents = cortex_search_service.search(
        query, columns=[], limit=st.session_state.num_retrieved_chunks
    )
    results = context_documents.results

    service_metadata = st.session_state.service_metadata
    search_col = [s["search_column"] for s in service_metadata
                    if s["name"] == st.session_state.selected_cortex_search_service][0]

    context_str = ""
    for i, r in enumerate(results):
        context_str += f"Context document {i+1}: {r[search_col]} \n" + "\n"

    if st.session_state.debug:
        st.sidebar.text_area("Context documents", context_str, height=500)

    return context_str

def get_chat_history():
    start_index = max(
        0, len(st.session_state.messages) - st.session_state.num_chat_messages
    )
    return st.session_state.messages[start_index : len(st.session_state.messages) - 1]

def complete(model, prompt):
    return session.sql("SELECT snowflake.cortex.complete(?,?)", (model, prompt)).collect()[0][0]

def make_chat_history_summary(chat_history, question):
    prompt = f"""
        [INST]
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natural language.
        Answer with only the query. Do not add any explanation.

        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        [/INST]
    """

    summary = complete(st.session_state.model_name, prompt)

    if st.session_state.debug:
        st.sidebar.text_area(
            "Chat history summary", summary.replace("$", "\$"), height=150
        )

    return summary

def create_prompt(user_question):
    if st.session_state.use_chat_history:
        chat_history = get_chat_history()
        if chat_history != []:
            question_summary = make_chat_history_summary(chat_history, user_question)
            prompt_context = query_cortex_search_service(question_summary)
        else:
            prompt_context = query_cortex_search_service(user_question)
    else:
        prompt_context = query_cortex_search_service(user_question)
        chat_history = ""

    prompt = f"""
            [INST]
            You are a helpful AI chat assistant with RAG capabilities. When a user asks you a question,
            you will also be given context provided between <context> and </context> tags. Use that context
            with the user's chat history provided in the between <chat_history> and </chat_history> tags
            to provide a summary that addresses the user's question. Ensure the answer is coherent, concise,
            and directly relevant to the user's question.

            If the user asks a generic question which cannot be answered with the given context or chat_history,
            just say "I don't know the answer to that question."

            Don't say things like "according to the provided context".

            <chat_history>
            {chat_history}
            </chat_history>
            <context>
            {prompt_context}
            </context>
            <question>
            {user_question}
            </question>
            [/INST]
            Answer:
        """
    return prompt

def main():
    st.title(f":speech_balloon: EV Docent")

    init_service_metadata()
    init_config_options()
    init_messages()

    icons = {"assistant": "❄️", "user": "👤"}

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=icons[message["role"]]):
            st.markdown(message["content"])

    disable_chat = (
        "service_metadata" not in st.session_state
        or len(st.session_state.service_metadata) == 0
    )
    if question := st.chat_input("Ask a question...", disabled=disable_chat):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        # Display user message in chat message container
        with st.chat_message("user", avatar=icons["user"]):
            st.markdown(question.replace("$", "\$"))

        # Display assistant response in chat message container
        with st.chat_message("assistant", avatar=icons["assistant"]):
            message_placeholder = st.empty()
            question = question.replace("'", "")
            with st.spinner("Thinking..."):
                generated_response = complete(
                    st.session_state.model_name, create_prompt(question)
                )
                message_placeholder.markdown(generated_response)

        st.session_state.messages.append(
            {"role": "assistant", "content": generated_response}
        )

if __name__ == "__main__":
    session = get_active_session()
    #session = Session.builder.configs(st.secrets.snowflake).create()
    root = Root(session)
    main()
