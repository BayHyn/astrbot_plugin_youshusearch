import asyncio
import aiohttp
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

        self.YS_PLATFORMS = {"他站", "本站", "起点", "晋江", "番茄", "刺猬猫", "纵横", "飞卢", "17K", "有毒", "息壤", "铁血", "逐浪", "掌阅", "塔读", "独阅读", "少年梦", "SF", "豆瓣", "知乎", "公众号"}
        self.YS_CATEGORIES = {"玄幻", "奇幻", "武侠", "仙侠", "都市", "现实", "军事", "历史", "悬疑", "游戏", "竞技", "科幻", "灵异", "二次元", "同人", "其他", "穿越时空", "架空历史", "总裁豪门", "都市言情", "仙侠奇缘", "幻想言情", "悬疑推理", "耽美纯爱", "衍生同人", "轻小说", "综合其他"}
        self.YS_STATUSES = {"连载中", "已完结", "已太监"}
        

    async def _perform_search(self, session: aiohttp.ClientSession, keyword: str, page: int = 1) -> Optional[tuple[List[Dict], int]]:
        """
        根据网站版本执行搜索。
        成功时返回一个元组: (结果列表, 总页数)。
        失败时返回 None。
        """
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
                        # API返回的结果字典已经很丰富，直接使用
                        results = data.get("data", []) 
                        total_pages = int(data.get("pageAll", 1))
                        return results, total_pages
                    else:
                        return None
            except Exception as e:
                logger.error(f"❌ 执行旧网址API搜索时发生错误: {e}", exc_info=True)
                return None

        elif self.api == 2:
            try:
                results_per_page = 20
                encoded_keyword = quote(keyword)
                search_url = urljoin(self.base_api_url, f"/search/all/{encoded_keyword}/{page}.html")
                logger.info(f"正在访问搜索URL: {search_url}")

                async with session.get(search_url, headers=self.headers, timeout=20) as response:
                    response.raise_for_status()
                    html_content = await response.text()
                
                def clean_html(raw_html):
                    return re.sub(r'<[^>]+>', '', raw_html).strip()

                # 判断页面类型
                if '共有<b class="hot">' in html_content:
                    logger.info("检测到搜索结果列表页，按列表解析。")
                    total_results = 0
                    total_match = re.search(r'共有<b class="hot">\s*(\d+)\s*</b>条结果', html_content)
                    if total_match:
                        total_results = int(total_match.group(1))
                    
                    total_pages = (total_results + results_per_page - 1) // results_per_page if total_results > 0 else 1
                    
                    results = []
                    result_blocks = re.findall(r'<div class="c_row">.*?<div class="cb"></div>', html_content, re.DOTALL)
                    
                    for block in result_blocks:
                        book_info = {}
                        # 提取书名和ID
                        name_match = re.search(r'<span class="c_subject"><a href="/book/(\d+)">(.*?)</a></span>', block, re.DOTALL)
                        if name_match:
                            book_info['id'] = int(name_match.group(1))
                            book_info['novel_name'] = clean_html(name_match.group(2))
                        
                        # 提取作者
                        author_match = re.search(r'<span class="c_label">作者：</span><span class="c_value">(.*?)</span>', block, re.DOTALL)
                        if author_match:
                            book_info['author_name'] = clean_html(author_match.group(1))
                        
                        # 提取评分
                        score_match = re.search(r'<span class="c_rr">([\d.]+)</span>', block)
                        if score_match:
                            book_info['score'] = score_match.group(1)
                        
                        # 提取评分人数
                        scorer_match = re.search(r'<span class="stard">\((\d+)人评分\)</span>', block)
                        if scorer_match:
                            book_info['scorer'] = scorer_match.group(1)
                        
                        if 'id' in book_info and 'novel_name' in book_info:
                            results.append(book_info)
                    
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

                # 提取标签
                novel_info['tags'] = []
                tag_block_match = re.search(r'<div class="tag-list"[^>]*?>(.*?)</div>', html_content, re.DOTALL)
                if tag_block_match:
                    tag_html = tag_block_match.group(1)
                    # 查找标签区块内的所有span标签内容
                    tags_list = re.findall(r'<span[^>]*?>(.*?)</span>', tag_html)
                    if tags_list:
                        # 清理并存储找到的标签
                        novel_info['tags'] = [tag.strip() for tag in tags_list if tag.strip()]

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
                
                novel_info.update({'platform': '无', 'category': '无', 'status': '无', 'word_number': None})
                info_exp_match = re.search(r'<div class="author-item-exp">(.*?)</div>', html_content, re.DOTALL)
                if info_exp_match:
                    # 1. 先用特殊字符替换分隔符
                    raw_text = info_exp_match.group(1).replace('<i class="author-item-line"></i>', '|')
                    # 2. 清理掉所有HTML标签
                    clean_text = re.sub(r'<[^>]+>', '', raw_text)
                    # 3. 按特殊字符分割
                    info_parts = [part.strip() for part in clean_text.split('|') if part.strip()]
                    
                    # 4. 遍历提取出的每个部分，进行智能分类
                    for part in info_parts:
                        if part in self.YS_PLATFORMS:
                            novel_info['platform'] = part
                        elif part in self.YS_CATEGORIES:
                            novel_info['category'] = part
                        elif part in self.YS_STATUSES:
                            novel_info['status'] = part
                        elif '字' in part:
                            word_match = re.search(r'(\d+)', part)
                            if word_match:
                                novel_info['word_number'] = float(word_match.group(1))

                novel_info['tags'] = []
                tag_section_match = re.search(r'<b>标签：</b>(.*?)</div>', html_content, re.DOTALL)
                if tag_section_match:
                    tag_block = tag_section_match.group(1)
                    tags = re.findall(r'<a[^>]*?>(.*?)</a>', tag_block)
                    if tags:
                        novel_info['tags'] = [clean_html_content(tag) for tag in tags]

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

            if not (novel_info and novel_info.get('novel_name', '无') != '无'):
                raise ValueError(f"无法从页面 {novel_id} 提取有效信息。")

            if novel_info and novel_info.get('novel_name', '无') != '无':
                message_text = f"---【{novel_info.get('novel_name', '无')}】---\n"
                message_text += f"作者: {novel_info.get('author_name', '无')}\n"

                if self.api == 2:
                    message_text += f"平台: {novel_info.get('platform', '未知')}\n"
                    message_text += f"分类: {novel_info.get('category', '未知')}\n"
                
                tags = novel_info.get('tags')
                if tags:
                    message_text += f"标签: {' '.join(tags)}\n"

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
            raise e
        except Exception as e:
            logger.error(f"解析书籍详情页失败: {e}", exc_info=True)
            raise e

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
                results_per_page = 20 if self.api == 2 else 15

                page_to_fetch = page_to_list
                if item_index is not None:
                    if item_index == 0:
                        yield event.plain_result("❌ 序号必须从1开始。")
                        return
                    page_to_fetch = (item_index - 1) // results_per_page + 1

                search_info = await self._perform_search(session, book_name, page=page_to_fetch)

                if search_info is None or (search_info[1] == 0 and page_to_fetch == 1 and not search_info[0]):
                    yield event.plain_result(f"😢 未找到关于【{book_name}】的任何书籍信息。")
                    return

                search_results, max_pages = search_info

                if page_to_fetch > max_pages and max_pages > 0:
                    yield event.plain_result(f"❌ 您请求的第 {page_to_fetch} 页不存在，【{book_name}】的搜索结果最多只有 {max_pages} 页。")
                    return

                if item_index is None and len(search_results) == 1 and max_pages == 1:
                    logger.info(f"🔍 搜索到唯一结果 for '{book_name}', 直接显示详情。")
                    selected_book = search_results[0]
                    novel_id = selected_book.get('id')
                    if not novel_id:
                        yield event.plain_result("❌ 无法获取该书籍的ID。")
                        return
                    
                    # 调用详情函数并返回
                    async for result in self._get_and_format_novel_details(event, session, str(novel_id)):
                        yield result
                    return


                if item_index is None:
                    start_num = (page_to_fetch - 1) * results_per_page + 1
                    message_text = f"以下是【{book_name}】的第 {page_to_fetch}/{max_pages} 页搜索结果:\n"
                    for i, book in enumerate(search_results):
                        num = start_num + i
                        name = book.get('novel_name', '未知书籍')
                        author = book.get('author_name', '未知作者')
                        score = book.get('score', 'N/A')
                        scorer = book.get('scorer', '0')
                        message_text += f"{num}. {name}\n    作者：{author} | 评分: {score} ({scorer}人)\n"
                    
                    message_text += f"\n💡 请使用 `/ys {book_name} <序号>` 查看详情"
                    if page_to_fetch < max_pages:
                        message_text += f"，或 `/ys {book_name} -{page_to_fetch + 1}` 翻页。"
                    yield event.plain_result(message_text)

                else:
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

    @filter.command("随机小说")
    async def youshu_random_command(self, event: AstrMessageEvent):
        """
        随机获取一本优书网上的小说信息。
        用法: /随机小说
        """
        max_retries = 10
        
        async with aiohttp.ClientSession() as session:
            try:
                latest_id = await self._get_latest_novel_id(session)
                if not latest_id:
                    yield event.plain_result("❌ 抱歉，未能获取到最新的小说ID，无法进行随机搜索。")
                    return
            except Exception as e:
                logger.error(f"获取最新ID时发生错误: {e}", exc_info=True)
                yield event.plain_result("❌ 获取最新小说ID时出错，请稍后再试。")
                return

            for attempt in range(max_retries):
                random_id = random.randint(1, latest_id)
                logger.info(f"第 {attempt + 1}/{max_retries} 次尝试随机ID: {random_id}")
                
                try:
                    async for result in self._get_and_format_novel_details(event, session, str(random_id)):
                        yield result
                    
                    return

                except aiohttp.ClientResponseError as e:
                    if e.status == 404:
                        logger.warning(f"页面 {random_id} 不存在 (404)，正在重试...")
                        continue # 捕获到404错误，静默重试
                    else:
                        logger.error(f"访问随机页面时发生HTTP错误: {e.status}", exc_info=True)
                        yield event.plain_result(f"❌ 访问随机页面时出错: HTTP {e.status}")
                        return
                except (ValueError, asyncio.TimeoutError) as e:
                    # 捕获解析失败或超时，也静默重试
                    logger.warning(f"处理随机ID {random_id} 失败: {e}，正在重试...")
                    continue
                except Exception as e:
                    logger.error(f"处理随机ID {random_id} 时发生未知错误: {e}", exc_info=True)
                    yield event.plain_result(f"❌ 处理随机书籍时发生未知错误。")
                    return

        yield event.plain_result("😢 抱歉，多次尝试后仍未找到有效的小说页面。请稍后再试。")

    async def terminate(self):
        """插件销毁时的清理工作"""
        logger.info("优书搜索插件已卸载")