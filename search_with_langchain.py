import concurrent.futures
import json
import re
from typing import Annotated, List, Generator, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


from loguru import logger

# 导入您的自定义 agent
from rag_chain import search_with_llm


# If the user did not provide a query, we will use this default query.
_default_query = "When was breath of the wild first released?"

# 创建一个 FastAPI 应用程序实例



# 定义pydantic模型
from pydantic import BaseModel
from typing import Optional
class QueryRequest(BaseModel):
    query: str 
    search_uuid: str
    generate_related_questions: Optional[bool] = True

# 定义fastapi中间件
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import ValidationError

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 打印接收到的请求信息
        logger.info(f"Request path: {request.url.path}")
        logger.info(f"Request method: {request.method}")
        # 打印请求头
        for name, value in request.headers.items():
            logger.info(f"Header {name}: {value}")

        # # 读取请求体
        body = await request.body()
        if body:
            # 打印请求体内容
            logger.info(f"Request body: \n {body}")
            # 尝试解析JSON内容（如果可能的话）
            try:
                body_json = json.loads(body.decode("utf-8"))
                logger.info(f"JSON parsed body: \n {body_json}")
            except json.JSONDecodeError:
                logger.info("Request body is not JSON")

        # 由于请求体已经被读取，需要将其内容放回原处
        request._body = body
        
        # 继续处理请求
        response = await call_next(request)

        return response
    
app = FastAPI()
app.add_middleware(RequestLoggingMiddleware)
# An executor to carry out async tasks.
executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)

# whether we should generate related questions.
should_do_related_questions = True


def _raw_stream_response(results) -> Generator[str, None, None]:
    """
    A generator that yields the raw stream response from processed results.
    
    Parameters:
    - results: A list of tuples, each containing a step name and data from the `search_with_llm` execution.
    """
    for step, data in results:
        if step == "contexts":
            # Yield the contexts as a JSON string
            yield json.dumps(data) + "\n\n__LLM_RESPONSE__\n\n"
        elif step == "llm_response":
            # Prepend a warning if necessary, then yield the LLM response
            if not data:
                yield "(The search engine returned nothing for this query. Please take the answer with a grain of salt.)\n\n"
            yield data
        elif step == "related_questions":
            # Try to dump the related questions as JSON, handle exceptions
            try:
                result = json.dumps(data)
            except Exception as e:
                result = "[]"
            yield "\n\n__RELATED_QUESTIONS__\n\n" + result


@app.post("/query")
async def query_function(body: QueryRequest) -> StreamingResponse:
# def query_function(query: str, search_uuid: str, generate_related_questions: Optional[bool] = True) -> StreamingResponse:
    """
    Query the search engine and returns the response.

    The query can have the following fields:
        - query: the user query.
        - generate_related_questions: if set to false, will not generate related
            questions. Otherwise, will depend on the environment variable
            RELATED_QUESTIONS. Default: true.
    """
    query = body.query
    search_uuid = body.search_uuid
    generate_related_questions = body.generate_related_questions
    logger.info(f"Received query: {query}")
    logger.info(f"Received search_uuid: {search_uuid}")
    logger.info(f"Received generate_related_questions: {generate_related_questions}")
    query = query or _default_query
    # Basic attack protection: remove "[INST]" or "[/INST]" from the query
    query = re.sub(r"\[/?INST\]", "", query)

    results = search_with_llm(query, generate_related_questions)

    return StreamingResponse(_raw_stream_response(results), media_type="text/plain")



app.mount("/ui", StaticFiles(directory="ui"), name="static")

@app.get("/")
async def index(request: Request):
    """
    Redirects "/" to the ui page.
    """
    return RedirectResponse(url="/ui/index.html")


if __name__ == "__main__":
    import uvicorn
    logger.info("Running LLM Server...")
    uvicorn.run(app, host="0.0.0.0", port=8080)