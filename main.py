import asyncio
import aiohttp
import json
import time
import random
import re
import base64
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
    "1.2",                         # 版本号
    "https://github.com/Foolllll-J/astrbot_plugin_youshusearch", # 插件仓库地址
)
class YoushuSearchPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        if config is None:
            config = {}
        self.search_api_endpoint = "api/novel/search"
        self.base_api_url = config.get("base_url", "https://www.ypshuo.com/")
        self.COOKIE_STRING = config.get("cookie", "")

        logger.info(f"优书搜索插件初始化，使用的基础URL: {self.base_api_url}")
        if self.base_api_url == "https://www.ypshuo.com/":
            self.api = 1
            self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        else:
            self.api = 2
            self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:143.0) Gecko/20100101 Firefox/143.0", 
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Cookie": self.COOKIE_STRING,
            "Referer": self.base_api_url
        }
        

    async def _perform_search(self, session: aiohttp.ClientSession, keyword: str, page: int = 1) -> Optional[List[Dict]]:
        """直接调用后端搜索API并解析JSON结果"""
        if self.api == 1:
            search_api_url = urljoin(self.base_api_url, self.search_api_endpoint)
            params = {"keyword": keyword, "page": str(page)}
            
            try:
                async with session.get(search_api_url, params=params, headers=self.headers, timeout=20) as response:
                    response.raise_for_status()
                    json_content = await response.json()
                    logger.info(f"搜索 '{keyword}' (Page {page}) API调用成功。")
                    
                    if json_content.get("code") == "00" and "data" in json_content:
                        data = json_content["data"]
                        results = data.get("data", [])
                        total_pages = int(data.get("pageAll", 1))
                        return results, total_pages
                    else:
                        return None
            except Exception as e:
                logger.error(f"❌ 执行网址API搜索时发生错误: {e}", exc_info=True)
                return None

        elif self.api == 2:
            try:
                encoded_keyword = quote(keyword)
                search_url = urljoin(self.base_api_url, f"/search/all/{encoded_keyword}/{page}.html")
                logger.info(f"正在访问搜索URL: {search_url}")

                async with session.get(search_url, headers=self.headers, timeout=20) as response:
                    response.raise_for_status()
                    html_content = await response.text()
                
                def clean_html(raw_html):
                    return re.sub(r'<[^>]+>', '', raw_html).strip()

                if '共有<b class="hot">' in html_content:
                    logger.info("检测到搜索结果列表页，按列表解析。")
                    total_results = 0
                    total_match = re.search(r'共有<b class="hot">\s*(\d+)\s*</b>条结果', html_content)
                    if total_match:
                        total_results = int(total_match.group(1))
                    
                    results_per_page = 20
                    total_pages = (total_results + results_per_page - 1) // results_per_page if total_results > 0 else 1
                    
                    results = []
                    result_blocks = re.findall(r'<div class="c_row">.*?<div class="cb"></div>', html_content, re.DOTALL)
                    for block in result_blocks:
                        match = re.search(r'<span class="c_subject"><a href="/book/(\d+)">(.*?)</a></span>', block, re.DOTALL)
                        if match:
                            book_id, novel_name_html = match.group(1), match.group(2)
                            results.append({'id': int(book_id), 'novel_name': clean_html(novel_name_html)})
                    
                    logger.info(f"成功从列表页解析到 {len(results)} 条结果，共 {total_pages} 页。")
                    return results, total_pages
                else:
                    logger.info("未找到搜索列表，尝试按单本书籍详情页解析...")
                    name_match = re.search(r'<title>(.*?)-.*?-优书网</title>', html_content)
                    id_match = re.search(r"uservote\.php\?id=(\d+)|rating\('\d+',\s*'(\d+)'\)|addbookcase\.php\?bid=(\d+)", html_content)

                    if name_match and id_match:
                        novel_id_str = next((gid for gid in id_match.groups() if gid is not None), None)
                        if novel_id_str:
                            novel_name = clean_html(name_match.group(1))
                            novel_id = int(novel_id_str)
                            logger.info(f"搜索结果为直接跳转，解析到书籍: '{novel_name}' (ID: {novel_id})")
                            
                            results = [{'id': novel_id, 'novel_name': novel_name}]
                            total_pages = 1
                            return results, total_pages

                    logger.warning("页面既不是搜索列表也不是有效的书籍详情页，判定为无结果。")
                    return [], 0

            except Exception as e:
                logger.error(f"❌ 执行新网址搜索时发生未知错误: {e}", exc_info=True)
                return None

    async def _get_latest_novel_id(self, session: aiohttp.ClientSession) -> Optional[int]:
        """获取最新的小说ID"""
        if self.api == 1:
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
        elif self.api == 2:
            url = "https://youshu.me/"
            try:
                async with session.get(url, headers=self.headers, timeout=10) as response:
                    response.raise_for_status()
                    html_content = await response.text()

                    new_book_section_match = re.search(
                        r'<div class="blocktitle">新书自助推荐.*?</div>\s*<div class="blockcontent">.*?</ul>',
                        html_content,
                        re.DOTALL
                    )

                    if not new_book_section_match:
                        logger.warning("❌ 未能在主页HTML中找到'新书自助推荐'区块。")
                        return None

                    new_book_block = new_book_section_match.group(0)
                    matches = re.findall(r'href="/book/(\d+)"', new_book_block)
                    
                    if matches:
                        latest_id = max([int(id) for id in matches])
                        logger.info(f"✅ 成功获取到最新的小说ID (youshu.me): {latest_id}")
                        return latest_id
                    else:
                        logger.warning("❌ 在'新书自助推荐'区块中未能找到任何小说ID。")
                        return None

            except aiohttp.ClientError as e:
                logger.error(f"❌ 访问主页失败 (youshu.me): 网络或HTTP错误 - {e}")
                return None
            except Exception as e:
                logger.error(f"❌ 获取最新小说ID时发生未知错误 (youshu.me): {e}", exc_info=True)
                return None

    async def _get_novel_details_from_html(self, html_content: str, novel_id: str) -> Dict:
        """
        从HTML响应中提取小说详细信息的辅助函数，使用更健壮的DOM解析。
        已修复封面图片获取逻辑。
        """
        def clean_html_content(text):
            if not text:
                return '无'
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
            text = re.sub(r'\.{3,}全文$', '...', text).strip()
            return text if text else '无'
        
        novel_info = {}
        
        if self.api == 1:
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
                review_item_regex = re.compile(
                    r'<div class="author-info"[^>]*?>(.*?)</div>'  # 第1捕获组: 作者名
                    r'.*?'                                         # 匹配中间所有内容
                    r'aria-valuenow="([^"]+)"'                      # 第2捕获组: 评分
                    r'.*?'                                         # 匹配中间所有内容
                    r'<span class="content-inner-details"[^>]*?>(.*?)</span>', # 第3捕获组: 评论内容
                    re.DOTALL
                )
                all_reviews = review_item_regex.findall(html_content)
                
                # 循环现在会解包出3个值
                for author, rating, content_block in all_reviews[:3]: 
                    content = re.sub(r'<[^>]+>', '', content_block)
                    content = re.sub(r'[\r\n\t]+', '', content).strip()
                    content = re.sub(r'\.{3,}全文$', '...', content).strip()
                    
                    if content:
                        reviews.append({
                            'author': author.strip(), # 添加作者名
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

        elif self.api == 2:
            try:
                # 提取书名
                name_match = re.search(r'<title>(.*?)-.*?-优书网</title>', html_content)
                novel_info['novel_name'] = clean_html_content(name_match.group(1)) if name_match else '无'

                # 提取作者名
                author_match = re.search(r'作者：<a.*?>(.*?)</a>', html_content)
                novel_info['author_name'] = clean_html_content(author_match.group(1)) if author_match else '无'
                
                # 提取评分和评分人数
                score_match = re.search(r'<span class="ratenum">(.*?)</span>', html_content)
                scorer_match = re.search(r'\((.*?)人已评\)', html_content)
                novel_info['score'] = clean_html_content(score_match.group(1)) if score_match else '无'
                novel_info['scorer'] = clean_html_content(scorer_match.group(1)) if scorer_match else '无'

                # 提取字数 (新网址，以字为单位)
                word_count_match = re.search(r'已完结<i[^>]*?></i>(\d+)字</div>', html_content)
                if word_count_match:
                    # 字数以 '字' 为单位，直接存储整数
                    novel_info['word_number'] = float(word_count_match.group(1).strip())
                else:
                    novel_info['word_number'] = None

                # 提取状态
                status_text = re.search(r'玄幻.*?<i[^>]*?></i>(.*?)<i[^>]*?></i>', html_content)
                novel_info['status'] = clean_html_content(status_text.group(1)) if status_text else '无'

                # 提取更新时间
                update_time_match = re.search(r'最后更新：(.*?)</td>', html_content)
                novel_info['update_time_str'] = clean_html_content(update_time_match.group(1)) if update_time_match else '无'

                # 提取简介
                synopsis_match = re.search(r'<div class="tabvalue"[^>]*?>\s*<div[^>]*?>(.*?)</div>', html_content, re.DOTALL)
                novel_info['synopsis'] = clean_html_content(synopsis_match.group(1)) if synopsis_match else '无'
                
                # 提取阅读链接
                link_match = re.search(r'<a class="btnlink b_hot mbs" href="(.*?)"', html_content)
                novel_info['link'] = clean_html_content(link_match.group(1)) if link_match else '无'

                # 提取封面图片
                img_match = re.search(r'<a[^>]*?class="book-detail-img"[^>]*?><img src="(.*?)"', html_content)
                novel_info['image_url'] = urljoin(self.base_api_url, img_match.group(1).strip()) if img_match and img_match.group(1).strip() else None
                
                reviews = []
                review_blocks = re.findall(r'<div class="c_row cf">.*?<div class="c_tag">', html_content, re.DOTALL)

                for block in review_blocks[:5]:
                    author_match = re.search(r'<p>(.*?)</p></a>\s*<p><div class="user-level">', block, re.DOTALL)
                    rating_match = re.search(r'<span title="(\d+)\s*颗星"', block, re.DOTALL)
                    content_match = re.search(r'<div class="c_description">(.*?)</div>', block, re.DOTALL)

                    if author_match and rating_match and content_match:
                        author = clean_html_content(author_match.group(1))
                        logger.info(f"author: {author}")
                        rating = rating_match.group(1)
                        content = clean_html_content(content_match.group(1))
                        logger.info(f"content: {content}")
                        if content and content != '无':
                            reviews.append({
                                'author': author,
                                'content': content,
                                'rating': rating
                            })
                
                novel_info['reviews'] = reviews
                return novel_info
                
            except Exception as e:
                logger.error(f"❌ DOM解析 (youshu.me) 失败。错误: {e}")
                logger.info(f"完整HTML响应内容: \n{html_content}")
                return {}
            
    async def _get_and_format_novel_details(self, event: AstrMessageEvent, session: aiohttp.ClientSession, novel_id: str):
        """
        根据小说ID获取、解析并格式化书籍详情。
        """
        if self.api == 1:
            novel_url = f"https://www.ypshuo.com/novel/{novel_id}.html"
        else:
            novel_url = f"https://youshu.me/book/{novel_id}"

        try:
            async with session.get(novel_url, headers=self.headers, timeout=10) as response:
                response.raise_for_status()
                html_content = await response.text()

            novel_info = await self._get_novel_details_from_html(html_content, str(novel_id))

            if novel_info and novel_info.get('novel_name', '无') != '无':
                message_text = f"---【{novel_info.get('novel_name', '无')}】---\n"
                message_text += f"作者: {novel_info.get('author_name', '无')}\n"
                word_number = novel_info.get('word_number')
                if word_number is not None and isinstance(word_number, (int, float)):
                    message_text += f"字数: {word_number / 10000:.2f}万字\n"
                else:
                    message_text += f"字数: 无\n"
                score = novel_info.get('score', '无')
                scorer = novel_info.get('scorer', '无')
                scorer_text = f"{scorer}人评分" if scorer and scorer != '无' else "无人评分"
                message_text += f"评分: {score} ({scorer_text})\n"
                message_text += f"状态: {novel_info.get('status', '无')}\n"
                message_text += f"更新: {novel_info.get('update_time_str', '无')}\n"
                synopsis = novel_info.get('synopsis', '无')
                message_text += f"简介: {synopsis[:200]}...\n"
                message_text += f"链接: {novel_info.get('link', novel_url)}\n"
                reviews = novel_info.get('reviews', [])
                if reviews:
                    message_text += "\n--- 📝 最新书评 ---\n"
                    for review in reviews:
                        author = review.get('author', '匿名')
                        rating = review.get('rating', '无')
                        content = review.get('content', '无')
                        message_text += f"{author} ({rating}分): {content}\n"
                
                chain = []
                if novel_info.get('image_url'):
                    image_url = novel_info['image_url']
                    try:
                        logger.info(f"正在尝试下载封面: {image_url}")
                        timeout = aiohttp.ClientTimeout(total=10)
                        async with session.get(image_url, timeout=timeout) as img_response:
                            img_response.raise_for_status()
                            image_bytes = await img_response.read()
                        
                        image_base64 = base64.b64encode(image_bytes).decode()
                        image_component = Comp.Image(file=f"base64://{image_base64}")
                        chain.append(image_component)

                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(f"❌ 下载封面图片失败 (超时或链接无效): {e}")
                        # 下载失败，仅在文本消息前添加提示
                        message_text = "🖼️ 封面加载失败\n\n" + message_text
                
                chain.append(Comp.Plain(message_text))
                yield event.chain_result(chain)
                
            else:
                yield event.plain_result(f"😢 无法从页面 {novel_id} 提取有效信息。")

        except aiohttp.ClientResponseError as e:
            logger.error(f"❌ 访问详情页 {novel_url} 失败，HTTP状态码: {e.status}")
            yield event.plain_result(f"❌ 访问书籍详情页失败。请尝试使用`/testys {novel_id}`。")
        except Exception as e:
            logger.error(f"解析书籍详情页失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 解析书籍详情页时发生错误。")

    @filter.command("ys") # 定义指令 /ys 书名 [序号 | -页码]
    async def youshu_search_command(self, event: AstrMessageEvent):
        """
        搜索有书网上的书籍信息。
        用法:
        - /ys <书名>: 显示第1页搜索结果列表。
        - /ys <书名> <序号>: 显示指定序号的书籍详情 (支持跨页)。
        - /ys <书名> -<页码>: 显示指定页码的搜索结果列表。
        """
        command_text = event.message_str.strip()
        command_parts = command_text.split()
        
        if not command_parts or command_parts[0].lower() != 'ys' or len(command_parts) < 2:
            yield event.plain_result("❌ 用法: /ys <书名> [序号 | -页码]")
            return

        args = command_parts[1:]
        book_name, page_to_list, item_index = "", 1, None
        last_arg = args[-1] if args else ""
        if len(args) > 1 and last_arg.startswith('-') and last_arg[1:].isdigit():
            page_to_list = int(last_arg[1:])
            if page_to_list == 0: page_to_list = 1
            book_name = " ".join(args[:-1]).strip()
        elif len(args) > 1 and last_arg.isdigit():
            item_index = int(last_arg)
            if item_index == 0: item_index = None
            book_name = " ".join(args[:-1]).strip()
        else:
            book_name = " ".join(args).strip()
        if not book_name:
            yield event.plain_result("❌ 请提供有效的书名进行搜索。")
            return

        logger.info(f"用户 {event.get_sender_id()} 触发 /ys, 搜索:'{book_name}', 序号:{item_index}, 列表页:{page_to_list}")
        
        try:
            async with aiohttp.ClientSession() as session:
                results_per_page = 20

                page_to_fetch = page_to_list
                if item_index is not None:
                    if item_index == 0:
                        yield event.plain_result("❌ 序号必须从1开始。")
                        return
                    page_to_fetch = (item_index - 1) // results_per_page + 1

                search_info = await self._perform_search(session, book_name, page=page_to_fetch)

                if search_info is None:
                    yield event.plain_result(f"😢 未找到关于【{book_name}】的书籍信息或请求失败。")
                    return

                search_results, max_pages = search_info

                if page_to_fetch > max_pages:
                    yield event.plain_result(f"❌ 您请求的第 {page_to_fetch} 页不存在，【{book_name}】的搜索结果最多只有 {max_pages} 页。")
                    return
                
                if not search_results and total_results == 0:
                    yield event.plain_result(f"😢 未找到关于【{book_name}】的任何书籍信息。")

                if item_index is None:
                    # --- 列表模式 ---
                    start_num = (page_to_fetch - 1) * results_per_page + 1
                    message_text = f"以下是【{book_name}】的第 {page_to_fetch}/{max_pages} 页搜索结果:\n"
                    for i, book in enumerate(search_results):
                        message_text += f"{start_num + i}. {book.get('novel_name', '未知书籍')}\n"
                    message_text += f"\n💡 请使用 `/ys {book_name} <序号>` 查看详情"
                    if page_to_fetch < max_pages:
                        message_text += f"，或 `/ys {book_name} -{page_to_fetch + 1}` 翻页。"
                    yield event.plain_result(message_text)

                else:
                    # --- 详情模式 ---
                    index_on_page = (item_index - 1) % results_per_page
                    
                    if not (0 <= index_on_page < len(search_results)):
                        yield event.plain_result(f"❌ 序号【{item_index}】在第 {page_to_fetch} 页上不存在。")
                        return

                    selected_book = search_results[index_on_page]
                    novel_id = selected_book.get('id')
                    if not novel_id:
                        yield event.plain_result(f"❌ 无法获取序号为【{item_index}】的书籍ID。")
                        return
                    
                    logger.info(f"🔍 用户选择序号 {item_index}, 计算页码 {page_to_fetch}, 书籍ID: {novel_id}")
                    
                    async for result in self._get_and_format_novel_details(event, session, str(novel_id)):
                        yield result

        except Exception as e:
            logger.error(f"搜索书籍 '{book_name}' 失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 搜索书籍时发生未知错误: {str(e)}")


    @filter.command("testys")
    async def testys_command(self, event: AstrMessageEvent, novel_id: str = "1"):
        """
        测试用指令，根据指定ID解析小说信息。
        用法: /testys [书目ID]
        示例: /testys 45830
        """
        yield event.plain_result(f"🧪 正在测试解析书目ID: 【{novel_id}】，请稍候...")
        if self.api == 1:
            novel_url = f"https://www.ypshuo.com/novel/{novel_id}.html"
        elif self.api == 2:
            novel_url = f"https://youshu.me/book/{novel_id}"

        try:
            async with aiohttp.ClientSession() as session:
                try:
                    logger.info(f"header: {self.headers}")
                    async with session.get(novel_url, headers=self.headers, timeout=10) as response:
                        response.raise_for_status()
                        if self.api == 2:
                            html_content = await response.text()
                            logger.info(f"使用UTF-8编码解析新网址 (youshu.me) 的响应内容。")
                        else:
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
                message_text += f"简介: {synopsis}\n"

                message_text += f"链接: {novel_info.get('link', novel_url)}\n"

                reviews = novel_info.get('reviews', [])
                if reviews:
                    message_text += "\n--- 📝 最新书评 ---\n"
                    if self.api == 1:
                        for i, review in enumerate(reviews):
                            message_text += f"书评{i+1} ({review.get('rating', '无')}分): {review.get('content', '无')}\n"
                    elif self.api == 2:
                        for i, review in enumerate(reviews):
                            message_text += f"{review.get('author', '无')} ({review.get('rating', '无')}分): {review.get('content', '无')}\n"
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
        max_retries = 5 # 最多重试5次
        
        async with aiohttp.ClientSession() as session:
            try:
                # 步骤1: 获取最新的小说ID作为随机范围的上限
                latest_id = await self._get_latest_novel_id(session)
                if not latest_id:
                    yield event.plain_result("❌ 抱歉，未能获取到最新的小说ID，无法进行随机搜索。")
                    return
            except Exception as e:
                logger.error(f"获取最新ID时发生错误: {e}", exc_info=True)
                yield event.plain_result("❌ 获取最新小说ID时出错，请稍后再试。")
                return

            # 步骤2: 循环尝试随机ID，直到成功或达到重试上限
            for attempt in range(max_retries):
                try:
                    random_id = random.randint(1, latest_id)
                    
                    # 根据网站版本生成不同格式的URL
                    if self.api == 1:
                        novel_url = f"https://www.ypshuo.com/novel/{random_id}.html"
                    else: # self.api == 2
                        novel_url = f"https://youshu.me/book/{random_id}"
                    
                    logger.info(f"第 {attempt + 1}/{max_retries} 次尝试随机ID: {random_id} -> {novel_url}")

                    # 步骤3: 访问随机页面
                    try:
                        async with session.get(novel_url, headers=self.headers, timeout=10) as response:
                            response.raise_for_status()
                            html_content = await response.text() # 无需指定编码，依赖请求头
                    except aiohttp.ClientResponseError as e:
                        if e.status == 404:
                            logger.warning(f"页面 {novel_url} 不存在 (404)，正在重试...")
                            continue # 页面不存在，直接进行下一次循环
                        else:
                            logger.error(f"访问 {novel_url} 时发生HTTP错误: {e.status}")
                            yield event.plain_result(f"❌ 访问随机页面时出错: HTTP {e.status}")
                            return

                    # 步骤4: 解析页面内容
                    novel_info = await self._get_novel_details_from_html(html_content, str(random_id))

                    if not novel_info or novel_info.get('novel_name', '无') == '无':
                        logger.warning(f"无法从页面 {random_id} 提取有效信息，正在重试...")
                        continue

                    # 步骤5: 格式化并发送成功信息
                    message_text = f"---【{novel_info.get('novel_name', '无')}】---\n"
                    message_text += f"作者: {novel_info.get('author_name', '无')}\n"
                    
                    word_number = novel_info.get('word_number')
                    if word_number is not None and isinstance(word_number, (int, float)):
                        message_text += f"字数: {word_number / 10000:.2f}万字\n"
                    else:
                        message_text += f"字数: 无\n"

                    score = novel_info.get('score', '无')
                    scorer = novel_info.get('scorer', '无')
                    scorer_text = f"{scorer}人评分" if scorer and scorer != '无' else "无人评分"
                    message_text += f"评分: {score} ({scorer_text})\n"

                    message_text += f"状态: {novel_info.get('status', '无')}\n"
                    message_text += f"更新: {novel_info.get('update_time_str', '无')}\n"

                    synopsis = novel_info.get('synopsis', '无')
                    message_text += f"简介: {synopsis}\n"

                    message_text += f"链接: {novel_info.get('link', novel_url)}\n"

                    reviews = novel_info.get('reviews', [])
                    if reviews:
                        message_text += "\n--- 📝 最新书评 ---\n"
                        for review in reviews:
                            author = review.get('author', '匿名')
                            rating = review.get('rating', '无')
                            content = review.get('content', '无')
                            message_text += f"{author} ({rating}分): {content}\n"
                    
                    chain = []
                    if novel_info.get('image_url'):
                        chain.append(Comp.Image.fromURL(novel_info['image_url']))
                    chain.append(Comp.Plain(message_text))

                    yield event.chain_result(chain)
                    return

                except Exception as e:
                    logger.error(f"处理随机ID {random_id} 时发生未知错误: {e}", exc_info=True)
                    # 单次尝试失败，循环会继续

        # 如果循环5次都失败了，发送最终的失败消息
        yield event.plain_result("😢 抱歉，多次尝试后仍未找到有效的小说页面。请稍后再试。")

    async def terminate(self):
        """插件销毁时的清理工作"""
        logger.info("优书搜索插件已卸载")
