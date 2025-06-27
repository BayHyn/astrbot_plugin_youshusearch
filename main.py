import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin, quote

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api import logger

@register(
    "astrbot_plugin_youshusearch", # 插件ID
    "Foolllll",                   # 作者名
    "优书搜索插件",                 # 插件显示名称
    "1.0.0",                      # 版本号
    "https://github.com/Foolllll-J/astrbot_plugin_youshusearch", # 插件仓库地址
)
class YoushuSearchPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.base_api_url = "https://www.ypshuo.com/"
        self.search_api_endpoint = "api/novel/search"
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }


    async def _perform_search(self, session: aiohttp.ClientSession, keyword: str, page: int = 1) -> Optional[List[Dict]]:
        """直接调用后端搜索API并解析JSON结果"""
        search_api_url = urljoin(self.base_api_url, self.search_api_endpoint)
        
        params = {
            "keyword": keyword,
            "page": str(page)
        }
        
        try:
            async with session.get(search_api_url, params=params, headers=self.headers, timeout=20) as response:
                response.raise_for_status()

                json_content = await response.json()
                
                logger.info(f"搜索 '{keyword}' API调用成功。JSON内容预览: {json.dumps(json_content, ensure_ascii=False)[:500]}...")

                if json_content.get("code") == "00" and json_content.get("data"):
                    return json_content["data"].get("data", [])
                else:
                    logger.warning(f"搜索API返回非成功代码或无数据: {json_content}")
                    return None

        except aiohttp.ClientError as e:
            logger.error(f"❌ 访问搜索API失败: 网络或HTTP错误 - {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"❌ 访问搜索API超时。")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"❌ 解析API响应JSON失败: {e}. 响应内容: {await response.text()}")
            raise
        except Exception as e:
            logger.error(f"❌ 执行搜索API时发生未知错误: {e}")
            raise


    # 修改此处：函数签名添加 session: aiohttp.ClientSession 参数
    async def _search_books_by_author(self, session: aiohttp.ClientSession, author_name: str) -> List[Dict]:
        """通过作者名搜索所有书籍，返回书名列表（直接调用API）"""
        results = await self._perform_search(session, author_name)
        if results:
            return [{'title': book.get('novel_name')} for book in results]
        return []

    # _get_book_details_from_page 函数不再需要，因为它已被移除

    @filter.command("ys") # 定义指令 /ys 书名
    async def youshu_search_command(self, event: AstrMessageEvent, book_name: str):
        """
        搜索有书网上的书籍信息。
        用法: /ys <书名>
        示例: /ys 诡秘之主
        """
        if not book_name:
            yield event.plain_result("❌ 请提供书名进行搜索。")
            return

        yield event.plain_result(f"📚 正在搜索书籍: 【{book_name}】，请稍候...")

        try:
            async with aiohttp.ClientSession() as session: # 确保整个搜索和锁定逻辑都在这个session块内
                search_results = await self._perform_search(session, book_name) # page默认为1

                if search_results:
                    locked_book = None
                    first_result = search_results[0] if search_results else None

                    if first_result: # 确保第一个结果存在才进行锁定判断
                        # --- 锁定逻辑 ---
                        # 关键词匹配的字段是 JSON 中的 'novel_name'
                        if book_name.lower() in first_result.get('novel_name', '').lower():
                            locked_book = first_result
                            logger.info(f"🔍 锁定书籍: 关键词 '{book_name}' 包含在书名 '{first_result.get('novel_name')}' 中。")
                        else:
                            # 比对作者，关键词匹配的字段是 JSON 中的 'author_name'
                            author_name = first_result.get('author_name', '').lower()
                            if book_name.lower() in author_name:
                                locked_book = first_result
                                logger.info(f"🔍 锁定书籍: 关键词 '{book_name}' 包含在作者名 '{first_result.get('author_name')}' 中。")
                                
                                # 进一步：搜索这个作者名，并返回所有书名 (此调用也会走API，返回JSON)
                                yield event.plain_result(f"💡 关键词未直接匹配书名，但匹配到作者【{first_result.get('author_name')}】。正在搜索该作者所有书籍...")
                                # 修改此处：将 session 作为参数传递给 _search_books_by_author
                                author_books = await self._search_books_by_author(session, first_result.get('author_name'))
                                if author_books:
                                    author_book_titles = "\n".join([f"• {b['title']}" for b in author_books])
                                    yield event.plain_result(f"✍️ 作者【{first_result.get('author_name')}】的作品列表:\n{author_book_titles}")
                                else:
                                    yield event.plain_result(f"❌ 未找到作者【{first_result.get('author_name')}】的其他书籍。")
                            else:
                                logger.info(f"🔍 未锁定书籍：关键词 '{book_name}' 未包含在书名或作者名中。")


                    if locked_book:
                        # 锁定到条目，直接从JSON数据返回详细信息
                        message = f"--- 📚 【{locked_book.get('novel_name', 'N/A')}】详细信息 ---\n"
                        message += f"✍️ 作者: {locked_book.get('author_name', 'N/A')}\n"
                        
                        if 'word_number' in locked_book and locked_book['word_number'] is not None:
                            message += f"字数: {locked_book['word_number'] / 10000:.2f}万字\n"
                        else:
                            message += f"字数: N/A\n"

                        status_map = {0: "连载中", 1: "已完结", 2: "已完结"}
                        message += f"状态: {status_map.get(locked_book.get('status', 0), 'N/A')}\n"
                        
                        message += f"评分: {locked_book.get('score', 'N/A')} ({locked_book.get('scorer', 'N/A')}人评分)\n"
                        
                        if 'update_time' in locked_book and locked_book['update_time'] is not None:
                            update_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(locked_book['update_time']))
                            message += f"更新: {update_date}\n"
                        else:
                            message += f"更新: N/A\n"
                        
                        message += f"简介: {locked_book.get('synopsis', 'N/A')[:200]}...\n"
                        
                        source_links = locked_book.get('source', '[]')
                        try:
                            source_links_parsed = json.loads(source_links)
                            if source_links_parsed and isinstance(source_links_parsed, list):
                                first_source_link = source_links_parsed[0].get('bookPage', 'N/A')
                                message += f"🔗 链接: {first_source_link}\n"
                            else:
                                message += f"🔗 链接: N/A\n"
                        except:
                            message += f"🔗 链接: N/A\n"

                        yield event.plain_result(message)
                    else:
                        # 未锁定，返回所有书目的书名
                        all_titles = "\n".join([f"• {b.get('novel_name', 'N/A')}" for b in search_results])
                        yield event.plain_result(f"以下是关于【{book_name}】的搜索结果:\n{all_titles}\n\n💡 如果想查看更多，请尝试更精确的书名。")

                else:
                    yield event.plain_result(f"😢 未找到关于【{book_name}】的书籍信息。")

        except Exception as e:
            logger.error(f"搜索书籍失败: {e}")
            yield event.plain_result(f"❌ 搜索书籍时发生错误: {str(e)}")

    async def terminate(self):
        """插件销毁时的清理工作"""
        logger.info("优书搜索插件已卸载")