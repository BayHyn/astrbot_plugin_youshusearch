import asyncio
import aiohttp
import json
import time
import random
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, quote

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import logger

@register(
    "astrbot_plugin_youshusearch",  # 插件ID
    "Foolllll",                    # 作者名
    "优书搜索插件",                  # 插件显示名称
    "1.1",                         # 版本号
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

    async def _get_latest_novel_id(self, session: aiohttp.ClientSession) -> Optional[int]:
        """获取优书网最新的小说ID"""
        url = "https://www.ypshuo.com/"
        try:
            async with session.get(url, headers=self.headers, timeout=10) as response:
                response.raise_for_status()
                html_content = await response.text()
                
                matches = re.findall(r'href="/novel/(\d+)\.html"', html_content)
                
                if matches:
                    latest_id = max([int(id) for id in matches])
                    logger.info(f"✅ 成功获取到最新的小说ID: {latest_id}")
                    return latest_id
                else:
                    logger.warning("❌ 未能在主页HTML中找到最新的小说ID。")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ 访问主页失败: 网络或HTTP错误 - {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 获取最新小说ID时发生未知错误: {e}")
            return None

    async def _get_novel_details_from_html(self, html_content: str, novel_id: str) -> Dict:
        """
        从HTML响应中提取小说详细信息的辅助函数，使用更健壮的DOM解析。
        已修复封面图片获取逻辑。
        """
        novel_info = {}

        try:
            # 1. 优先从OGP元标签中提取封面图片URL
            og_image_match = re.search(r'<meta[^>]*?name="og:image"[^>]*?content="(.*?)"', html_content)
            if og_image_match:
                image_url = og_image_match.group(1)
                # 确保URL是完整的
                if image_url.startswith('//'):
                    image_url = 'https:' + image_url
                elif image_url.startswith('/'):
                    image_url = urljoin(self.base_api_url, image_url)
                novel_info['image_url'] = image_url
                logger.info(f"提取到的封面URL (从OGP标签): {image_url}")
            else:
                # 2. 如果OGP标签不存在，再回退到原来的正则匹配方法
                image_match = re.search(r'<img src="(.*?)"[^>]*?class="book-img"', html_content)
                if image_match:
                    image_url = image_match.group(1)
                    if image_url.startswith('/'):
                        image_url = urljoin(self.base_api_url, image_url)
                    novel_info['image_url'] = image_url
                    logger.info(f"提取到的封面URL (从<img>标签): {image_url}")
                else:
                    novel_info['image_url'] = None
                    logger.warning("未能从页面中提取到封面图片URL。")


            # 提取书名
            name_match = re.search(r'<h1 class="book-name".*?>(.*?)</h1>', html_content, re.DOTALL)
            novel_info['novel_name'] = name_match.group(1).strip() if name_match else '无'
            
            # 提取作者名
            author_match = re.search(r'作者：<span class="text-red-500".*?>(.*?)</span>', html_content)
            novel_info['author_name'] = author_match.group(1).strip() if author_match else '无'

            # 提取字数
            word_count_match = re.search(r'字数：(.*?)万字', html_content)
            if word_count_match:
                try:
                    word_str = word_count_match.group(1).strip().replace(',', '')
                    novel_info['word_number'] = float(word_str) * 10000
                except (ValueError, TypeError):
                    novel_info['word_number'] = None
            else:
                novel_info['word_number'] = None
            
            # 提取评分和评分人数
            score_data_matches = re.findall(r'<div class="item"[^>]*?>\s*<p class="score"[^>]*?>\s*(.*?)\s*</p>\s*<p[^>]*?>(.*?)</p>\s*</div>', html_content, re.DOTALL)
            
            novel_info['score'] = '无'
            novel_info['scorer'] = '无'

            for value, label in score_data_matches:
                if label.strip() == '评分':
                    novel_info['score'] = value.strip()
                elif label.strip() == '评分人数':
                    novel_info['scorer'] = value.strip()
            
            # 提取状态
            status_match = re.search(r'状态：\s*(.*?)\s*<', html_content)
            novel_info['status'] = status_match.group(1).strip() if status_match else '无'

            # 提取更新时间
            update_time_match = re.search(r'更新时间：\s*(.*?)\s*</div>', html_content)
            novel_info['update_time_str'] = update_time_match.group(1).strip() if update_time_match else '无'
            
            reviews = []
            review_item_regex = re.compile(r'<div class="item"[^>]*?>.*?<div class="discuss-content"[^>]*?>.*?<span class="content-inner-details"[^>]*?>(.*?)</span>.*?</div>.*?</div>.*?<div class="novel-rate"[^>]*?><div role="slider" aria-valuenow="([^"]+)"', re.DOTALL)
            all_reviews = review_item_regex.findall(html_content)
            
            for review_data in all_reviews[:3]: 
                content_block, rating = review_data
                
                content = re.sub(r'<[^>]+>', '', content_block)
                content = re.sub(r'[\r\n\t]+', '', content).strip()
                
                if content:
                    reviews.append({
                        'content': content,
                        'rating': rating
                    })

            novel_info['reviews'] = reviews
            
            # 提取简介
            synopsis_match = re.search(r'<div style="white-space:pre-wrap;"[^>]*?>(.*?)</div>', html_content, re.DOTALL)
            synopsis_content = synopsis_match.group(1).strip() if synopsis_match else '无'
            novel_info['synopsis'] = synopsis_content
            
            # 提取链接
            link_match = re.search(r'<a href="(http.*?)".*?rel="nofollow".*?>', html_content)
            novel_info['link'] = link_match.group(1).strip() if link_match else '无'

            return novel_info
            
        except Exception as e:
            logger.error(f"❌ DOM解析失败。错误: {e}")
            return {}

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

        try:
            async with aiohttp.ClientSession() as session:
                search_results = await self._perform_search(session, book_name)

                if search_results:
                    locked_book = None
                    for book in search_results:
                        if book.get('novel_name', '').lower().strip() == book_name.lower().strip():
                            locked_book = book
                            break
                    
                    if locked_book:
                        novel_id = locked_book.get('id')
                        
                        if novel_id:
                            logger.info(f"🔍 锁定精确书籍，ID: {novel_id}")
                            novel_url = f"https://www.ypshuo.com/novel/{novel_id}.html"
                            
                            try:
                                async with session.get(novel_url, headers=self.headers, timeout=10) as response:
                                    response.raise_for_status()
                                    html_content = await response.text()
                                
                                novel_info = await self._get_novel_details_from_html(html_content, str(novel_id))
                                
                                if novel_info and novel_info.get('novel_name'):
                                    message_text = f"---【{novel_info.get('novel_name', '无')}】详细信息 ---\n"
                                    message_text += f"作者: {novel_info.get('author_name', '无')}\n"
                                    
                                    word_number = novel_info.get('word_number')
                                    if word_number is not None and isinstance(word_number, (int, float)):
                                        message_text += f"字数: {word_number / 10000:.2f}万字\n"
                                    else:
                                        message_text += f"字数: 无\n"

                                    score = novel_info.get('score', '无')
                                    scorer = novel_info.get('scorer', '无')
                                    message_text += f"评分: {score} ({scorer}人评分)\n"

                                    message_text += f"状态: {novel_info.get('status', '无')}\n"
                                    message_text += f"更新: {novel_info.get('update_time_str', '无')}\n"

                                    synopsis = novel_info.get('synopsis', '无')
                                    message_text += f"简介: {synopsis[:200]}...\n"

                                    message_text += f"🔗 链接: {novel_info.get('link', novel_url)}\n"

                                    reviews = novel_info.get('reviews', [])
                                    if reviews:
                                        message_text += "\n--- 📝 最新书评 ---\n"
                                        for i, review in enumerate(reviews):
                                            message_text += f"书评{i+1} ({review.get('rating', '无')}分): {review.get('content', '无')}\n"
                                    
                                    chain = []
                                    if novel_info.get('image_url'):
                                        chain.append(Comp.Image.fromURL(novel_info['image_url']))
                                    chain.append(Comp.Plain(message_text))

                                    yield event.chain_result(chain)
                                    return
                            
                            except aiohttp.ClientResponseError as e:
                                logger.error(f"❌ 访问页面 {novel_url} 失败，HTTP状态码: {e.status}")
                                yield event.plain_result(f"❌ 访问书籍详情页失败。请尝试使用`/testys {novel_id}`。")
                            except Exception as e:
                                logger.error(f"解析书籍详情页失败: {e}")
                                yield event.plain_result(f"❌ 解析书籍详情页时发生错误: {str(e)}。")

                    else:
                        all_titles = "\n".join([f"• {b.get('novel_name', '无')}" for b in search_results])
                        yield event.plain_result(f"以下是关于【{book_name}】的搜索结果:\n{all_titles}\n\n💡 如果想查看更多，请尝试更精确的书名。")

                else:
                    yield event.plain_result(f"😢 未找到关于【{book_name}】的书籍信息。")

        except Exception as e:
            logger.error(f"搜索书籍失败: {e}")
            yield event.plain_result(f"❌ 搜索书籍时发生错误: {str(e)}")

    @filter.command("testys")
    async def testys_command(self, event: AstrMessageEvent, novel_id: str = "1"):
        """
        测试用指令，根据指定ID解析小说信息。
        用法: /testys [书目ID]
        示例: /testys 45830
        """
        yield event.plain_result(f"🧪 正在测试解析书目ID: 【{novel_id}】，请稍候...")

        try:
            async with aiohttp.ClientSession() as session:
                novel_url = f"https://www.ypshuo.com/novel/{novel_id}.html"
                try:
                    async with session.get(novel_url, headers=self.headers, timeout=10) as response:
                        response.raise_for_status()
                        html_content = await response.text()
                except aiohttp.ClientResponseError as e:
                    yield event.plain_result(f"❌ 访问页面 {novel_url} 失败，HTTP状态码: {e.status}")
                    return

                novel_info = await self._get_novel_details_from_html(html_content, novel_id)

                if not novel_info or not novel_info.get('novel_name'):
                    yield event.plain_result(f"😢 无法从页面 {novel_id} 提取有效信息，请检查ID或重试。")
                    return

                # 格式化并返回信息
                message_text = f"--- ✅ 【{novel_info.get('novel_name', '无')}】 (测试解析) ---\n"
                message_text += f"✍️ 作者: {novel_info.get('author_name', '无')}\n"
                
                word_number = novel_info.get('word_number')
                if word_number is not None and isinstance(word_number, (int, float)):
                    message_text += f"字数: {word_number / 10000:.2f}万字\n"
                else:
                    message_text += f"字数: 无\n"

                score = novel_info.get('score', '无')
                scorer = novel_info.get('scorer', '无')
                message_text += f"评分: {score} ({scorer}人评分)\n"

                message_text += f"状态: {novel_info.get('status', '无')}\n"
                message_text += f"更新: {novel_info.get('update_time_str', '无')}\n"

                synopsis = novel_info.get('synopsis', '无')
                message_text += f"简介: {synopsis[:200]}...\n"

                message_text += f"🔗 链接: {novel_info.get('link', novel_url)}\n"

                reviews = novel_info.get('reviews', [])
                if reviews:
                    message_text += "\n--- 📝 最新书评 ---\n"
                    for i, review in enumerate(reviews):
                        message_text += f"书评{i+1} ({review.get('rating', '无')}分): {review.get('content', '无')}\n"
                
                chain = []
                if novel_info.get('image_url'):
                    chain.append(Comp.Image.fromURL(novel_info['image_url']))
                chain.append(Comp.Plain(message_text))

                yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"测试解析小说失败: {e}")
            yield event.plain_result(f"❌ 测试解析时发生错误: {str(e)}")

    @filter.command("随机小说")
    async def youshu_random_command(self, event: AstrMessageEvent):
        """
        随机获取一本优书网上的小说信息。
        用法: /随机小说
        """
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    latest_id = await self._get_latest_novel_id(session)
                    if not latest_id:
                        yield event.plain_result("❌ 抱歉，未能获取到最新的小说ID，无法进行随机搜索。")
                        return
                    
                    random_id = random.randint(1, latest_id)
                    novel_url = f"https://www.ypshuo.com/novel/{random_id}.html"
                    logger.info(f"第 {attempt + 1} 次尝试随机ID: {random_id}")

                    try:
                        async with session.get(novel_url, headers=self.headers, timeout=10) as response:
                            response.raise_for_status()
                            html_content = await response.text()
                    except aiohttp.ClientResponseError as e:
                        if e.status == 404:
                            logger.warning(f"页面 {novel_url} 不存在，正在重试...")
                            continue
                        else:
                            raise

                    novel_info = await self._get_novel_details_from_html(html_content, str(random_id))

                    if not novel_info or not novel_info.get('novel_name'):
                        logger.warning(f"无法从页面 {random_id} 提取有效信息，正在重试...")
                        continue

                    # 格式化并返回信息
                    message_text = f"---【{novel_info.get('novel_name', '无')}】---\n"
                    
                    author_name = novel_info.get('author_name', '无')
                    if not author_name:
                        author_name = '无'
                    message_text += f"作者: {author_name}\n"
                    
                    word_number = novel_info.get('word_number')
                    if word_number is not None and isinstance(word_number, (int, float)):
                        message_text += f"字数: {word_number / 10000:.2f}万字\n"
                    else:
                        message_text += f"字数: 无\n"

                    score = novel_info.get('score', '无')
                    scorer = novel_info.get('scorer', '无')
                    message_text += f"评分: {score} ({scorer}人评分)\n"

                    message_text += f"状态: {novel_info.get('status', '无')}\n"
                    message_text += f"更新: {novel_info.get('update_time_str', '无')}\n"

                    synopsis = novel_info.get('synopsis', '无')
                    message_text += f"简介: {synopsis[:200]}...\n"

                    message_text += f"🔗 链接: {novel_info.get('link', novel_url)}\n"

                    reviews = novel_info.get('reviews', [])
                    if reviews:
                        message_text += "\n--- 📝 最新书评 ---\n"
                        for i, review in enumerate(reviews):
                            message_text += f"书评{i+1} ({review.get('rating', '无')}分): {review.get('content', '无')}\n"
                    
                    chain = []
                    if novel_info.get('image_url'):
                        chain.append(Comp.Image.fromURL(novel_info['image_url']))
                    chain.append(Comp.Plain(message_text))

                    yield event.chain_result(chain)
                    return

            except Exception as e:
                logger.error(f"随机获取小说失败: {e}")
                yield event.plain_result(f"❌ 随机获取小说时发生错误: {str(e)}")
                return
        
        yield event.plain_result("😢 抱歉，多次尝试后仍未找到有效的小说页面。请稍后再试。")

    async def terminate(self):
        """插件销毁时的清理工作"""
        logger.info("优书搜索插件已卸载")
