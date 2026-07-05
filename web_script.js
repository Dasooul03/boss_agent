// ==UserScript==
// @name         Job Seeker
// @namespace    http://tampermonkey.net/
// @version      2026.06.26.7
// @description  Job Seeker 篡改猴插件
// @author       Chatbot-Zhou
// @match        https://www.zhipin.com/*
// @icon         https://www.google.com/s2/favicons?sz=64&domain=zhipin.com
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @grant        GM_openInTab
// @connect      127.0.0.1
// @connect      localhost
// @updateURL    http://127.0.0.1:33333/web_script.user.js
// @downloadURL  http://127.0.0.1:33333/web_script.user.js
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';
    // OriginalAuthor: 嘎嘎脆的贝爷

    // 配置项
    const OPTIONS = {
        scriptVersion: '2026.06-cli-autogreet.23',
        greetMaxAttempts: 3,
        greetRetryDelays: [0, 3000, 8000],
        resumeIndex: 0, // 第几份简历，从 0 开始递增
        serverHost: 'http://127.0.0.1:33333', // 本地服务的主机地址
        thread: 60, // 分数阈值，低于这个就不发消息
        timestampTimeout: 120000, // 页面跳转来源标记有效期，单位毫秒
        jobInfoResponseTimeout: 90000, // 详情页回传职位信息的最长等待时间
        onlyGreet: true, // 仅辅助打招呼，不自动扫描普通聊天页
        sessionGreetLimit: 50,
        actionDelayMs: 2500,
        manualInterventionMaxRetries: 3,
        searchLeaseMs: 12000,
        openCooldownMs: 45000,
        recentProcessedHours: 24,
    };

    let backendOfflineNotified = false;
    let backendOfflineFailures = 0;
    const BACKEND_OFFLINE_NOTIFY_THRESHOLD = 2;
    const PAGE_INSTANCE_ID = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

    function applyBackendConfig(config) {
        if (!config) return;
        if (Number.isFinite(Number(config.score_threshold))) {
            OPTIONS.thread = Number(config.score_threshold);
        }
        if (Number.isFinite(Number(config.session_greet_limit))) {
            OPTIONS.sessionGreetLimit = Number(config.session_greet_limit);
        }
    }

    // 元素选择器
    const SELECTORS = {
        ZHIPIN: {
            SEARCH: {
                SEARCHINPUT: 'input', // 搜索框
                SEARCHBTN: '.search-btn', // 搜索按钮
                JOBLISTCTN: '.job-list-container', // 职位列表容器
                JOBLIST: '.rec-job-list', // 职位列表
                JOBHREFS: '.job-card-box .job-name', // 职位链接
                JOBLIST_CANDIDATES: ['.rec-job-list', '.job-list-box', '.job-list-container', '.search-job-result'],
                JOBHREFS_CANDIDATES: ['.job-card-box .job-name', '.job-card-wrapper .job-title a', 'a[href*="/job_detail/"]'],
            },
            DETAIL: {
                STARTCHAT: [
                    '.btn-startchat',
                    '.btn-chat',
                    '[ka*="start_chat"]',
                    '[ka*="geek_chat"]',
                    'a[href*="/web/geek/chat"]',
                    'a[href*="/geek/chat"]',
                    'button[class*="startchat"]',
                    'button[class*="chat"]',
                ], // 开始聊天按钮
                NAMEBOX: '.name', // 职位名称盒子
                JOBNAME: 'h1', // 职位名称
                SALARY: '.salary', // 职位薪资
                DETAIL: '.job-sec-text', // 职位详情
                CHATURL: 'redirect-url', // 聊天链接
                JOBNAME_CANDIDATES: ['.job-banner .name h1', '.job-primary .name h1', '.info-primary .name h1', '.name h1', 'h1'],
                SALARY_CANDIDATES: ['.job-banner .salary', '.job-primary .salary', '.info-primary .salary', '.name .salary', '.salary'],
                DETAIL_CANDIDATES: ['.job-sec-text', '.job-detail-section .text', '.job-description', '[class*="job-sec-text"]'],
                COMPANY_CANDIDATES: ['.company-info .name', '.company-name', '.job-detail-company .name', '.sider-company .name', '.company-card .name', '.job-company-info .name'],
                CITY_CANDIDATES: ['.job-location', '.location-address', '.job-address', '.job-area', '.city'],
            },
            CHAT: {
                // 聊天
                CHATINPUT: [
                    '#chat-input',
                    '.chat-input [contenteditable="true"]',
                    '.input-area [contenteditable="true"]',
                    'textarea[id*="chat"]',
                    'textarea[class*="chat"]',
                    '[contenteditable="true"]',
                ], // 聊天输入框
                MSGSEND: [
                    '.btn-send',
                    '[class*="btn-send"]',
                    '[ka*="send"]',
                    'button[class*="send"]:not(.disabled)',
                ], // 消息发送按钮
                // 聊天记录
                HISTORYCTN: '.chat-message', // 聊天记录容器
                USEFULMSG: '.item-friend,.item-myself', // 有效的文字聊天记录项
                MSGCONTENT: '.message-content .text', // 聊天记录内容
                // 职位
                JOBEL: '*[ka=geek_chat_job_detail]', // 职位元素
                JOBCITY: '.city', // 职位城市
            }
        },
    };

    // 搜索路径
    const SEARCHPATH = {
        zhipin: '/web/geek/job',
    };

    // 白名单
    const WHITELIST = {
        zhipin: {
            detail: ['/job_detail', '/web/geek/job_detail'],
            chat: ['/web/geek/chat']
        },
    };

    // 宸ュ叿
    const tools = {
        inWhiteList: function (pathObj) {
            return Object.values(pathObj).some((path) => {
                const list = Array.isArray(path) ? path : [path];
                return list.some(item => location.pathname.startsWith(item) || location.pathname.includes(item));
            });
        },
        pathMatches(pathObj) {
            const list = Array.isArray(pathObj) ? pathObj : [pathObj];
            return list.some(item => location.pathname.startsWith(item) || location.pathname.includes(item));
        },
        isSearchPath(path = location.pathname) {
            return path.startsWith(SEARCHPATH.zhipin) || path.includes(SEARCHPATH.zhipin);
        },
        isCityHomePath(path = location.pathname) {
            return /^\/[a-z][a-z0-9-]*\/?$/.test(path);
        },
        findOne(selectors, root = document) {
            const list = Array.isArray(selectors) ? selectors : [selectors];
            for (const selector of list) {
                try {
                    const el = root.querySelector(selector);
                    if (el) return el;
                } catch (e) {
                    // Ignore stale or unsupported selectors and continue fallback list.
                }
            }
            return null;
        },
        textOf(selectors, root = document) {
            const el = this.findOne(selectors, root);
            return el ? el.innerText.trim() : '';
        },
        endlessFind: function (selector, timeout = 10000) {
            return new Promise((resolve, reject) => {
                // 初始立即检查元素是否存在
                let element;
                try {
                    element = this.findOne(selector);
                } catch (e) {
                    reject(e); // 处理无效选择器
                    return;
                }
                if (element) {
                    resolve(element);
                    return;
                }

                // 设置超时
                const timeoutId = setTimeout(() => {
                    observer.disconnect();
                    const platformLimit = this.detectPlatformLimit();
                    if (platformLimit) {
                        reject(new Error(`平台次数限制: ${platformLimit}`));
                        return;
                    }
                    const interruption = this.detectManualInterruption();
                    if (interruption) {
                        reject(new Error(`需要人工处理: ${interruption}`));
                        return;
                    }
                    reject(new Error(`未找到目标元素: ${Array.isArray(selector) ? selector.join(', ') : selector}`));
                }, timeout);

                // 定义 MutationObserver 回调
                const observer = new MutationObserver((_, obs) => {
                    try {
                        const el = this.findOne(selector);
                        if (el) {
                            obs.disconnect();
                            clearTimeout(timeoutId);
                            resolve(el);
                        }
                    } catch (e) {
                        obs.disconnect();
                        clearTimeout(timeoutId);
                        reject(e);
                    }
                });

                // 开始观察整个文档的 DOM 变化
                observer.observe(document.documentElement, {
                    childList: true,
                    subtree: true
                });
            });
        },
        waitForOne(selectors, timeout = 10000) {
            const list = Array.isArray(selectors) ? selectors : [selectors];
            return new Promise((resolve, reject) => {
                const existing = this.findOne(list);
                if (existing) {
                    resolve(existing);
                    return;
                }
                const startedAt = Date.now();
                const observer = new MutationObserver((_, obs) => {
                    const el = this.findOne(list);
                    if (el) {
                        obs.disconnect();
                        clearTimeout(timeoutId);
                        resolve(el);
                    }
                });
                const timeoutId = setTimeout(() => {
                    observer.disconnect();
                    const platformLimit = this.detectPlatformLimit();
                    if (platformLimit) {
                        reject(new Error(`平台次数限制: ${platformLimit}`));
                        return;
                    }
                    const interruption = this.detectManualInterruption();
                    if (interruption) {
                        reject(new Error(`需要人工处理: ${interruption}`));
                        return;
                    }
                    reject(new Error(`未找到目标元素: ${list.join(', ')}, 等待 ${Date.now() - startedAt}ms`));
                }, timeout);
                observer.observe(document.documentElement, {
                    childList: true,
                    subtree: true,
                });
            });
        },
        inputText: function (el, text) {
            el.value = text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        },
        inputEditableText: function (el, text) {
            if ('value' in el) {
                el.focus();
                el.value = text;
                el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return String(el.value || '').trim();
            }
            el.focus();
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(el);
            selection.removeAllRanges();
            selection.addRange(range);
            document.execCommand('delete', false);
            const inserted = document.execCommand('insertText', false, text);
            if (!inserted || !el.innerText.includes(text)) {
                el.innerText = text;
                el.textContent = text;
            }
            el.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Process' }));
            el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Process' }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            selection.removeAllRanges();
            return el.innerText.trim() || el.textContent.trim() || '';
        },
        elementBrief(el) {
            if (!el) return {};
            return {
                tag: el.tagName || '',
                id: el.id || '',
                className: String(el.className || ''),
                text: String(el.innerText || el.textContent || '').trim().slice(0, 80),
                role: el.getAttribute ? (el.getAttribute('role') || '') : '',
                ka: el.getAttribute ? (el.getAttribute('ka') || '') : '',
            };
        },
        isVisible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        },
        isDisabled(el) {
            if (!el) return true;
            const disabledAttr = el.disabled
                || el.getAttribute('disabled') !== null
                || el.getAttribute('aria-disabled') === 'true';
            const classText = String(el.className || '').toLowerCase();
            const parentClassText = String(el.parentElement?.className || '').toLowerCase();
            return Boolean(disabledAttr)
                || classText.includes('disabled')
                || classText.includes('forbid')
                || parentClassText.includes('disabled')
                || parentClassText.includes('forbid');
        },
        asyncSleep(ms) {
            return new Promise((resolve) => setTimeout(resolve, ms));
        },
        actionSleep(baseMs = OPTIONS.actionDelayMs) {
            const jitter = Math.floor(Math.random() * 1200);
            return this.asyncSleep(baseMs + jitter);
        },
        readJson(key, fallback = {}) {
            try {
                return JSON.parse(localStorage.getItem(key) || '') || fallback;
            } catch (e) {
                return fallback;
            }
        },
        writeJson(key, value) {
            localStorage.setItem(key, JSON.stringify(value));
        },
        getTimestamp(key) {
            return Number(localStorage.getItem(key));
        },
        openCooldownKey(key, href) {
            return `__job_seeker_open_cooldown:${key}:${this.normalUrl(href) || href}`;
        },
        canOpenUrl(href, key, cooldownMs = OPTIONS.openCooldownMs) {
            const cooldownKey = this.openCooldownKey(key, href);
            const previous = Number(localStorage.getItem(cooldownKey) || 0);
            return !previous || Date.now() - previous > cooldownMs;
        },
        markOpenUrl(href, key) {
            localStorage.setItem(this.openCooldownKey(key, href), String(Date.now()));
        },
        closeTabHandle(handle) {
            try {
                if (handle && typeof handle.close === 'function') {
                    handle.close();
                    return true;
                }
            } catch (e) {
                return false;
            }
            return false;
        },
        openTabNSetTimestamp(href, key, self = false, options = {}) {
            localStorage.setItem(key, new Date().getTime());

            if (self) {
                location.href = href;
                return true;
            }
            if (!options.force && !this.canOpenUrl(href, key, options.cooldownMs || OPTIONS.openCooldownMs)) {
                return null;
            }
            this.markOpenUrl(href, key);

            if (typeof GM_openInTab === 'function') {
                return GM_openInTab(href, {
                    active: false,
                    insert: true,
                    setParent: true,
                });
            }

            return window.open(href, key);
        },
        absoluteUrl(href) {
            if (!href) return '';
            try {
                return new URL(href, location.origin).href;
            } catch (e) {
                return href;
            }
        },
        normalUrl(href) {
            const absolute = this.absoluteUrl(href);
            if (!absolute) return '';
            if (absolute.startsWith('javascript:') || absolute === location.href || absolute.endsWith('#')) {
                return '';
            }
            return absolute;
        },
        findUrlDeep(value, matcher, depth = 0, seen = new Set()) {
            if (!value || depth > 5) return '';
            if (typeof value === 'string') {
                const url = this.normalUrl(value);
                return url && matcher(url) ? url : '';
            }
            if (typeof value !== 'object' || seen.has(value)) return '';
            seen.add(value);
            if (Array.isArray(value)) {
                for (const item of value) {
                    const found = this.findUrlDeep(item, matcher, depth + 1, seen);
                    if (found) return found;
                }
                return '';
            }
            const likelyKeys = ['chatUrl', 'redirectUrl', 'redirect-url', 'url', 'href', 'link'];
            const entries = Object.entries(value).sort(([a], [b]) => {
                const aLikely = likelyKeys.some(key => a.toLowerCase().includes(key.toLowerCase()));
                const bLikely = likelyKeys.some(key => b.toLowerCase().includes(key.toLowerCase()));
                return Number(bLikely) - Number(aLikely);
            });
            for (const [, item] of entries) {
                const found = this.findUrlDeep(item, matcher, depth + 1, seen);
                if (found) return found;
            }
            return '';
        },
        findChatUrlDeep(value) {
            return this.findUrlDeep(value, url => this.isChatUrl(url));
        },
        isChatUrl(url) {
            return Boolean(url && (url.includes('/web/geek/chat') || url.includes('/geek/chat')));
        },
        hrefFromJobNode(node) {
            if (!node) return '';
            const direct = node.matches && node.matches('a[href]') ? node : null;
            const closest = node.closest ? node.closest('a[href]') : null;
            const child = node.querySelector ? node.querySelector('a[href]') : null;
            const link = direct || closest || child;
            return link ? this.normalUrl(link.getAttribute('href') || link.href) : '';
        },
        greetContextKey: '__chatbot_zhou_greet_context',
        greetClaimKey: '__chatbot_zhou_greet_claim',
        newGreetRequestId() {
            return `greet_${Date.now()}_${Math.floor(Math.random() * 100000)}_${PAGE_INSTANCE_ID}`;
        },
        getGreetContext() {
            return this.readJson(this.greetContextKey, {});
        },
        saveGreetContext(context) {
            const next = {
                ...context,
                requestId: String(context.requestId || this.newGreetRequestId()),
                createdAt: Number(context.createdAt || Date.now()),
                maxAttempts: Number(context.maxAttempts || OPTIONS.greetMaxAttempts || 3),
                attempt: Number(context.attempt || 1),
            };
            this.writeJson(this.greetContextKey, next);
            return next;
        },
        clearGreetContext(requestId = '') {
            const context = this.getGreetContext();
            if (requestId && context.requestId && context.requestId !== requestId) return false;
            localStorage.removeItem(this.greetContextKey);
            const claim = this.readJson(this.greetClaimKey, {});
            if (!requestId || claim.requestId === requestId) {
                localStorage.removeItem(this.greetClaimKey);
            }
            return true;
        },
        claimGreetContext() {
            const context = this.getGreetContext();
            if (!context || !context.requestId) {
                return { claimed: false, reason: 'missing_request_id', context };
            }
            const createdAt = Number(context.createdAt || 0);
            if (!createdAt || Date.now() - createdAt > OPTIONS.timestampTimeout) {
                return { claimed: false, reason: 'expired', context };
            }
            const claim = this.readJson(this.greetClaimKey, {});
            const claimExpired = !claim.claimedAt || Date.now() - Number(claim.claimedAt) > OPTIONS.timestampTimeout;
            if (claim.requestId === context.requestId && claim.pageInstanceId && claim.pageInstanceId !== PAGE_INSTANCE_ID && !claimExpired) {
                return { claimed: false, reason: 'claimed_by_other_page', context, claim };
            }
            const nextClaim = {
                requestId: context.requestId,
                pageInstanceId: PAGE_INSTANCE_ID,
                claimedAt: Date.now(),
                url: location.href,
            };
            this.writeJson(this.greetClaimKey, nextClaim);
            const confirmed = this.readJson(this.greetClaimKey, {});
            const claimed = confirmed.requestId === context.requestId && confirmed.pageInstanceId === PAGE_INSTANCE_ID;
            return { claimed, reason: claimed ? '' : 'claim_race_lost', context, claim: confirmed };
        },
        releaseGreetClaim(requestId = '') {
            const claim = this.readJson(this.greetClaimKey, {});
            if (claim.pageInstanceId !== PAGE_INSTANCE_ID) return false;
            if (requestId && claim.requestId !== requestId) return false;
            localStorage.removeItem(this.greetClaimKey);
            return true;
        },
        claimTimestampGreetFallback(openedAt) {
            const fallbackId = `timestamp_${openedAt || 0}`;
            const claim = this.readJson(this.greetClaimKey, {});
            const claimExpired = !claim.claimedAt || Date.now() - Number(claim.claimedAt) > OPTIONS.timestampTimeout;
            if (claim.requestId === fallbackId && claim.pageInstanceId && claim.pageInstanceId !== PAGE_INSTANCE_ID && !claimExpired) {
                return { claimed: false, reason: 'fallback_claimed_by_other_page', claim };
            }
            const nextClaim = {
                requestId: fallbackId,
                pageInstanceId: PAGE_INSTANCE_ID,
                claimedAt: Date.now(),
                url: location.href,
                fallback: true,
            };
            this.writeJson(this.greetClaimKey, nextClaim);
            const confirmed = this.readJson(this.greetClaimKey, {});
            const claimed = confirmed.requestId === fallbackId && confirmed.pageInstanceId === PAGE_INSTANCE_ID;
            return { claimed, reason: claimed ? 'timestamp_fallback_claimed' : 'fallback_claim_race_lost', claim: confirmed };
        },
        sessionStateKey: '__chatbot_zhou_greet_session',
        getGreetSession() {
            try {
                const value = JSON.parse(localStorage.getItem(this.sessionStateKey) || '{}');
                return {
                    runId: String(value.runId || ''),
                    backendRunId: String(value.backendRunId || ''),
                    count: Number(value.count || 0),
                    startedAt: String(value.startedAt || ''),
                    ended: Boolean(value.ended),
                };
            } catch (e) {
                return { runId: '', backendRunId: '', count: 0, startedAt: '', ended: true };
            }
        },
        saveGreetSession(session) {
            const state = {
                runId: String(session.runId || ''),
                backendRunId: String(session.backendRunId || ''),
                count: Math.max(0, Number(session.count || 0)),
                startedAt: String(session.startedAt || new Date().toISOString()),
                ended: Boolean(session.ended),
            };
            localStorage.setItem(this.sessionStateKey, JSON.stringify(state));
            return state;
        },
        startGreetSession(force = false, backendRunId = '') {
            const current = this.getGreetSession();
            if (!force && current.runId && !current.ended && (!backendRunId || current.backendRunId === backendRunId)) {
                return current;
            }
            return this.saveGreetSession({
                runId: `run_${Date.now()}_${Math.floor(Math.random() * 100000)}`,
                backendRunId,
                count: 0,
                startedAt: new Date().toISOString(),
                ended: false,
            });
        },
        endGreetSession() {
            const current = this.getGreetSession();
            if (!current.runId) return current;
            return this.saveGreetSession({ ...current, ended: true });
        },
        getSessionGreetCount() {
            return this.getGreetSession().count;
        },
        increaseSessionGreetCount() {
            const current = this.startGreetSession(false);
            const next = this.saveGreetSession({ ...current, count: current.count + 1, ended: false });
            return next.count;
        },
        detectInterruptionText(text) {
            const content = String(text || '').replace(/\s+/g, ' ');
            const patterns = [
                '安全验证',
                '访问异常',
                '请完成验证',
                '登录已过期',
                '请先登录',
                '账号存在异常',
                '访问过于频繁',
                '系统检测到异常',
                '拖动滑块',
                '向右滑动',
                '滑动验证',
                '图形验证码',
                '请输入验证码',
                '完成验证码',
                'captcha',
                'verify',
                'login',
            ];
            return patterns.find(pattern => content.includes(pattern)) || '';
        },
        detectPlatformLimitText(text) {
            const content = String(text || '').replace(/\s+/g, ' ');
            const patterns = [
                '次数已用完',
                '次数已达上限',
                '达到上限',
                '今日无法继续沟通',
                '今日沟通次数',
                '今日招呼次数',
                '明日再试',
                '明天再试',
                '今日已达上限',
                '沟通名额已用完',
                '打招呼次数已用完',
                '操作过于频繁',
                'limit',
                'too frequent',
            ];
            return patterns.find(pattern => content.includes(pattern)) || '';
        },
        detectManualInterruption() {
            const text = document.body ? document.body.innerText : '';
            return this.detectInterruptionText(text);
        },
        detectPlatformLimit() {
            const text = document.body ? document.body.innerText : '';
            return this.detectPlatformLimitText(text);
        },
        manualInterruptionReason(value) {
            const content = String(value || '');
            const detected = this.detectInterruptionText(content);
            if (detected) return detected;
            return content.slice(0, 120);
        },
        isManualInterruptionError(value) {
            return Boolean(this.manualInterruptionReason(value) && this.detectInterruptionText(String(value || '')));
        },
        platformLimitReason(value) {
            const content = String(value || '');
            const detected = this.detectPlatformLimitText(content);
            if (detected) return detected;
            return '';
        },
        isPlatformLimitError(value) {
            return Boolean(this.platformLimitReason(value));
        },
        isElementMissingError(value) {
            const content = String(value || '');
            return content.includes('未找到目标元素') || content.includes('target element') || content.includes('not found');
        },
        contactedReasonFromElement(el) {
            if (!el) return '';
            const text = String(el.innerText || el.textContent || '').replace(/\s+/g, '');
            const attrText = [
                el.getAttribute && el.getAttribute('ka'),
                el.getAttribute && el.getAttribute('class'),
                el.getAttribute && el.getAttribute('data-isfriend'),
                el.dataset && el.dataset.isfriend,
            ].filter(Boolean).join(' ');
            if (el.dataset && el.dataset.isfriend === 'true') return '页面标记已沟通';
            const contactedPatterns = ['继续沟通', '去聊天', '已沟通', '沟通中', '查看聊天', '进入聊天'];
            const matched = contactedPatterns.find(pattern => text.includes(pattern));
            if (matched) return `页面显示${matched}`;
            if (String(attrText).includes('isfriend') && String(attrText).includes('true')) {
                return '页面属性标记已沟通';
            }
            return '';
        },
    };

    /**
     * 横幅
     * @param {string} text 显示的文本
     */
    function banner(text) {
        const el = document.createElement('div');
        el.style.cssText = `
                position: fixed;
                top: 60px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 9999;
                background-color: rgba(0,0,0,.5);
                padding: 4px 20px;
                text-align: center;
                border-radius: 8px;
                color: #fff;
        `;
        el.innerText = text;
        document.body.appendChild(el);
        setTimeout(function () {
            el.remove();
        }, 3000);
    }

    /**
     * 转换时间
     * @param {number} seconds 秒数
     * @returns {string} 转换后的时间字符串
     */
    function convertTime(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;

        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toFixed(0).padStart(2, '0')}`;
    }


    class WebBroadcastError extends Error {
        constructor(code, message) {
            super(message);
            this.code = code;
            this.name = 'WebBroadcastError';
        }
    }

    class WebBroadcast {
        static ID_COUNTER = 0; // 自增序列，避免时间戳冲突

        /**
         * @param {string} name 频道名称
         * @param {string} target 当前页面标识
         * @param {object} [options] 配置项
         * @param {number} [options.retry=3] 发送失败重试次数
         * @param {number} [options.retryInterval=1000] 重试间隔(毫秒)
         */
        constructor(name, target, options = {}) {
            this.name = name;
            this.target = target;
            this.retry = options.retry ?? 3;
            this.retryInterval = options.retryInterval ?? 1000;
            this.evts = {};
            this.pendingResponses = {};
            this.pendingReceives = {};

            // 初始化通信通道
            this.initChannel();
        }

        /* -------------------- 核心通信逻辑 -------------------- */
        initChannel() {
            // 优先使用 BroadcastChannel
            if (typeof BroadcastChannel !== 'undefined') {
                this.setupBroadcastChannel();
            } else {
                this.setupStorageFallback();
            }
            window.addEventListener('beforeunload', () => this.destroy());
        }

        setupBroadcastChannel() {
            this.channelType = 'broadcast';
            this.channel = new BroadcastChannel(this.name);
            this.channel.addEventListener('message', this.handleMessage.bind(this));
            this.channel.addEventListener('messageerror', (e) => {
                this.emitError('MESSAGE_ERROR', '消息解析失败', e);
            });
        }

        setupStorageFallback() {
            this.channelType = 'storage';
            this.storageKey = `web_broadcast_${this.name}`;

            // 监听 storage 事件
            window.addEventListener('storage', (e) => {
                if (e.key === this.storageKey && e.newValue) {
                    const message = JSON.parse(e.newValue);
                    this.handleMessage({ data: message });
                }
            });
        }

        handleMessage(e) {
            const resp = e.data;
            if (![this.target, 'all'].includes(resp.to)) return;

            // 处理事件监听
            if (this.evts[resp.type]) {
                Promise.resolve().then(() => this.evts[resp.type](resp.from, resp.data));
            }

            // 处理 receive 等待
            const receiveKey = `${resp.from}-${resp.type}`;
            if (this.pendingReceives[receiveKey]) {
                const pending = this.pendingReceives[receiveKey];
                pending.resolve(resp.data);
                clearTimeout(pending.timer);
                delete this.pendingReceives[receiveKey];
            }

            // 处理 sendAndReceive 响应
            if (this.pendingResponses[resp.data?.requestId]) {
                const pending = this.pendingResponses[resp.data.requestId];
                pending.resolve(resp.data);
                clearTimeout(pending.timer);
                delete this.pendingResponses[resp.data.requestId];
            }
        }

        /* -------------------- 消息收发方法 -------------------- */
        send(to, type, data = null, attempt = 0) {
            const message = { from: this.target, to, type, data };

            return new Promise((resolve, reject) => {
                try {
                    if (this.channelType === 'broadcast') {
                        this.channel.postMessage(message);
                    } else {
                        // storage 方案需要先写入再删除，以触发事件
                        localStorage.setItem(this.storageKey, JSON.stringify(message));
                        localStorage.removeItem(this.storageKey);
                    }
                    resolve();
                } catch (err) {
                    if (attempt < this.retry) {
                        setTimeout(() => this.send(to, type, data, attempt + 1), this.retryInterval);
                    } else {
                        this.emitError('SEND_FAILED', `消息发送失败: ${type}`, err);
                        reject(`消息发送失败: ${type}, ${err.message}`);
                    }
                }
            });
        }

        receive(from, type, timeout = 30000) {
            const key = `${from}-${type}`;
            return new Promise((resolve, reject) => {
                const timer = setTimeout(() => {
                    reject(new WebBroadcastError('TIMEOUT', `接收超时: ${type}`));
                    delete this.pendingReceives[key];
                }, timeout);

                this.pendingReceives[key] = { resolve, reject, timer };
            });
        }

        sendAndReceive(to, type, data = null, timeout = 30000) {
            const requestId = this.generateRequestId();
            const responseType = `${type}_response`;

            return new Promise((resolve, reject) => {
                const timer = setTimeout(() => {
                    reject(new WebBroadcastError('TIMEOUT', `请求超时: ${type}`));
                    delete this.pendingResponses[requestId];
                }, timeout);


                this.pendingResponses[requestId] = { resolve, reject, timer };
                // 发送时携带 responseType
                this.send(to, type, { ...data, requestId, responseType });
            });
        }

        reply(originalFrom, originalType, data, requestId, responseType) {
            const finalResponseType = responseType || `${originalType}_response`;
            return this.send(originalFrom, finalResponseType, { ...data, requestId });
        }

        /* -------------------- 工具方法 -------------------- */
        generateRequestId() {
            const time = Date.now().toString(36);
            const random = Math.random().toString(36).slice(2, 6);
            WebBroadcast.ID_COUNTER = (WebBroadcast.ID_COUNTER + 1) % 0xfff;
            return `${time}-${random}-${WebBroadcast.ID_COUNTER.toString(36).padStart(2, '0')}`;
        }

        emitError(code, message, error) {
            const err = new WebBroadcastError(code, `${message}: ${error?.message || error}`);
            console.error(err);
            if (this.evts['error']) {
                this.evts['error'](code, err.message);
            }
        }

        on(evt, fn) {
            if (typeof fn !== 'function') throw new Error('callback must be a function');
            this.evts[evt] = fn;
        }

        off(evt) {
            delete this.evts[evt];
        }

        destroy() {
            if (this.channel) {
                this.channel.close();
            }
            window.removeEventListener('storage', this.handleMessage);
            this.pendingResponses = {};
            this.pendingReceives = {};
        }
    }

    // API 请求
    class Api {
        constructor() { }

        /**
         * 封装请求
         * @param {string} path 请求路径
         * @param {string} method 请求方法
         * @param {any} data 请求数据
         * @returns {Promise<any>} 请求结果
         */
        __http(path, method = 'GET', data = null) {
            return new Promise(async (resolve, reject) => {
                const hasLegacyRequest = typeof GM_xmlhttpRequest !== 'undefined';
                const hasPromiseRequest = typeof GM !== 'undefined' && GM.xmlHttpRequest;
                const request = hasLegacyRequest ? GM_xmlhttpRequest : (hasPromiseRequest ? GM.xmlHttpRequest : null);
                if (!request) {
                    banner('缺少 GM.xmlHttpRequest 权限');
                    reject('缺少 GM.xmlHttpRequest 权限');
                    return;
                }
                const handleResponse = (resp) => {
                    if (resp.status != 200) {
                        banner(`请求失败: ${resp.status}`);
                        reject(resp.status);
                        return;
                    }
                    try {
                        const raw = resp.responseText ?? resp.response ?? '{}';
                        resolve(typeof raw === 'string' ? JSON.parse(raw) : raw);
                    } catch (e) {
                        banner('响应解析失败');
                        reject(`响应解析失败: ${e}`);
                    }
                };
                const handleError = (err) => {
                    const message = err?.error || err?.message || err?.statusText || JSON.stringify(err);
                    banner(`请求出错: ${path}`);
                    reject(`请求出错: ${path} ${message}`);
                };
                const options = {
                    method: method,
                    url: OPTIONS.serverHost + path,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    data: data,
                    timeout: 1000 * 60 * 10,
                    onload: handleResponse,
                    onerror: handleError,
                    ontimeout: handleError,
                };
                try {
                    const result = request(options);
                    if (!hasLegacyRequest && result && typeof result.then === 'function') {
                        result.then(handleResponse).catch(handleError);
                    }
                } catch (err) {
                    handleError(err);
                }
            });
        }

        /**
         * 获取自我介绍
         */
        getIntroduce() {
            return new Promise((resolve, reject) => this.__http('/get-introduce').then(res => {
                resolve(res.introduce);
            }).catch(reject));
        }

        /**
         * 获取标签
         */
        getTags() {
            return new Promise((resolve, reject) => this.__http('/tags').then(res => {
                resolve(res.tags);
            }).catch(reject));
        }

        getRecentJobs() {
            return this.__http(`/jobs/recent?limit=800&hours=${OPTIONS.recentProcessedHours}`)
                .then(res => Array.isArray(res.jobs) ? res.jobs : [])
                .catch(() => []);
        }

        /**
         * 上报脚本状态
         */
        heartbeat(page, status = 'running', currentAction = '', detail = {}) {
            return this.__http('/script/heartbeat', 'POST', JSON.stringify({
                page,
                status,
                current_action: currentAction,
                detail,
            })).catch(() => ({
                control: 'paused',
                should_pause: true,
                should_start: false,
                should_stop: false,
                offline: true,
                message: '后端未连接，已暂停脚本动作',
            }));
        }

        control(command) {
            return this.__http('/control', 'POST', JSON.stringify({ command }));
        }

        event(type, message, source = 'script', level = 'info', detail = {}) {
            return this.__http('/events', 'POST', JSON.stringify({
                type,
                source,
                level,
                message,
                detail,
            })).catch(() => null);
        }

        /**
         * 结构化职位分析
         */
        analyzeJob(jobInfo) {
            return this.__http('/jobs/analyze', 'POST', JSON.stringify(jobInfo)).then(res => res.analysis);
        }

        /**
         * 创建待确认动作
         */
        createAction(actionType, payload = {}, jobInfo = {}, status = 'pending') {
            return this.__http('/actions', 'POST', JSON.stringify({
                action_type: actionType,
                status,
                job_url: jobInfo.url || '',
                company: jobInfo.company || '',
                title: jobInfo.title || '',
                payload,
            }));
        }

        getAction(id) {
            return this.__http(`/actions/${id}`);
        }

        async waitActionApproved(id, timeout = 1000 * 60 * 10) {
            const start = Date.now();
            while (Date.now() - start < timeout) {
                const action = await this.getAction(id);
                if (action.status === 'approved') return true;
                if (action.status === 'rejected') return false;
                await tools.asyncSleep(2000);
            }
            return false;
        }
    }

    // 日志记录
    class Logger {
        constructor(startFn, pauseFn) {
            // 校验回调函数
            if (startFn && typeof startFn !== 'function') {
                throw new Error('参数错误：startFn 应为函数');
            }
            if (pauseFn && typeof pauseFn !== 'function') {
                throw new Error('参数错误：pauseFn 应为函数');
            }
            // 创建元素
            const ctn = document.createElement('div');
            const btnBox = document.createElement('div');
            const clearBtn = document.createElement('div');
            const runBtn = document.createElement('div');
            const foldBtn = document.createElement('div');
            const msgList = document.createElement('div');
            ctn.style.cssText = `
                position: fixed;
                bottom: 16px;
                left: 16px;
                width: 380px;
                background-color: rgba(0, 0, 0, 0.5);
                color: #fff;
                z-index: 9999;
                font-size: 14px;
                border-radius: 10px;
            `;
            btnBox.style.cssText = `
                width: 380px;
                height: 32px;
                display: flex;
                align-items: center;
                justify-content: flex-end;
            `;
            clearBtn.style.cssText = runBtn.style.cssText = foldBtn.style.cssText = `
                width: 60px;
                height: 32px;
                line-height: 32px;
                text-align: center;
                cursor: pointer;
            `;
            msgList.style.cssText = `
                width: 380px;
                height: 240px;
                padding: 2px 12px 8px;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 4px;
            `;
            clearBtn.innerText = "清空";
            runBtn.innerText = "开始";
            foldBtn.innerText = "收起";
            document.body.appendChild(ctn);
            ctn.appendChild(btnBox);
            btnBox.appendChild(clearBtn);
            btnBox.appendChild(runBtn);
            btnBox.appendChild(foldBtn);
            ctn.appendChild(msgList);
            this.ctn = ctn;
            this.list = msgList;
            this.runBtn = runBtn;
            this.clearBtn = clearBtn;
            this.__startFn = startFn || (() => void 0);
            this.__pauseFn = pauseFn || (() => void 0);
            this.__pause = true;
            clearBtn.addEventListener('click', () => this.clear());
            runBtn.addEventListener('click', async () => {
                const nextPaused = !this.__pause;
                this.setPaused(nextPaused);
                try {
                    if (nextPaused) {
                        await this.__pauseFn();
                    } else {
                        await this.__startFn();
                    }
                } catch (e) {
                    this.add(`控制命令发送失败: ${e}`);
                }
            });
            foldBtn.addEventListener('click', () => {
                if (foldBtn.innerText === "展开") {
                    msgList.style.height = "240px";
                    foldBtn.innerText = "收起";
                } else {
                    msgList.style.height = "32px";
                    this.list.scrollTop = this.list.scrollHeight;
                    foldBtn.innerText = "展开";
                }
            });
        }

        setPaused(paused) {
            this.__pause = Boolean(paused);
            this.runBtn.innerText = this.__pause ? "继续" : "暂停";
        }

        add(message) {
            const item = document.createElement('div');
            item.textContent = message;
            this.list.appendChild(item);
            this.list.scrollTop = this.list.scrollHeight;
        }

        divider() {
            const item = document.createElement('div');
            item.style.cssText = `
                width: 100%;
                border-top: 1px dashed rgba(255, 255, 255, 0.6);
            `;
            this.list.appendChild(item);
            this.list.scrollTop = this.list.scrollHeight;
        }

        clear() {
            while (this.list.firstChild) {
                this.list.removeChild(this.list.firstChild);
            }
        }

        remove() {
            this.ctn.remove();
        }
    }

    // BOSS 直聘
    class Zhipin {
        constructor() {
            // 窗口标签
            this.targets = {
                search: "__zhipin_search",
                detail: "__zhipin_detail",
                chat: "__zhipin_chat",
                chatGreet: "__zhipin_chat_greet",
            };
            // 广播类型
            this.bcTypes = {
                // 全局
                STATUS: "status",
                RUN: 'run',
                DIVIDER: 'divider',
                INTRODUCE: 'introduce',
                HEART_BEAT: 'heart-beat',
                // 聊天页和职位详情页
                GET_JOB_INFO: 'get-job-info',
                SAY_HI: 'say-hi',
            };
            // 白名单
            this.whiteList = WHITELIST.zhipin;
            // 记录状态
            this.pause = false;
            this.tags = [];
            this.introduce = ''
        }

        // 注册广播
        __broadcast(target) {
            this.broadcast = new WebBroadcast('__zhipin_broadcast', target);
        }

        // 搜索页
        async __search(tagIdx) {
            // api
            const api = new Api();
            let currentTagIdx = Math.max(0, Number(tagIdx) || 0);
            this.pause = true;
            const searchPageOpenedAt = new Date().getTime();
            const nowMs = () => (
                window.performance && typeof window.performance.now === 'function'
                    ? window.performance.now()
                    : Date.now()
            );
            let runStartedAt = 0;
            let processedCount = 0;
            let totalProcessedMs = 0;
            let currentJobProgress = null;
            let page = 0;
            // 记录职位链接
            let jobHrefs = [];
            let elsLen = 0;
            const seenJobHrefs = new Set();
            const backendProcessedHrefs = new Set();
            let lastJobListEventKey = '';
            // 缓存
            let started = false;
            let booting = false;
            let loopRunning = false;
            let waitingForGreeting = false;
            let greetTimeoutId = null;
            let activeGreetingJob = null;
            let currentSearchAction = '等待启动';
            let lastBackendControl = 'paused';
            let lastBackendRunId = '';
            let hasSearchLease = false;
            let leaseTimer = null;
            let activeTempTab = null;
            const searchLeaseKey = '__job_seeker_search_lease';
            const manualRecoveryStateKey = '__job_seeker_manual_recovery';
            let manualInterventionRetryCount = 0;
            const pageFailureStateKey = '__job_seeker_page_failure_recovery';
            let pageFailureRetryCount = 0;

            const loadManualRecoveryState = () => {
                try {
                    const state = JSON.parse(localStorage.getItem(manualRecoveryStateKey) || '{}');
                    if (!state || !state.timestamp || Date.now() - Number(state.timestamp) > 5 * 60 * 1000) {
                        return {};
                    }
                    return state;
                } catch (e) {
                    return {};
                }
            };

            const saveManualRecoveryState = (state) => {
                localStorage.setItem(manualRecoveryStateKey, JSON.stringify({
                    ...state,
                    timestamp: Date.now(),
                }));
            };

            const clearManualRecoveryState = () => {
                localStorage.removeItem(manualRecoveryStateKey);
            };

            const loadPageFailureState = () => {
                try {
                    const state = JSON.parse(localStorage.getItem(pageFailureStateKey) || '{}');
                    if (!state || !state.timestamp || Date.now() - Number(state.timestamp) > 5 * 60 * 1000) {
                        return {};
                    }
                    return state;
                } catch (e) {
                    return {};
                }
            };

            const savePageFailureState = (state) => {
                localStorage.setItem(pageFailureStateKey, JSON.stringify({
                    ...state,
                    timestamp: Date.now(),
                }));
            };

            const clearPageFailureState = () => {
                localStorage.removeItem(pageFailureStateKey);
            };

            const loadedManualRecovery = loadManualRecoveryState();
            if (Number.isFinite(Number(loadedManualRecovery.nextTagIdx))) {
                currentTagIdx = Math.max(0, Number(loadedManualRecovery.nextTagIdx));
            }
            if (Number.isFinite(Number(loadedManualRecovery.retryCount))) {
                manualInterventionRetryCount = Math.max(0, Number(loadedManualRecovery.retryCount));
            }
            const loadedPageFailure = loadPageFailureState();
            if (Number.isFinite(Number(loadedPageFailure.retryCount))) {
                pageFailureRetryCount = Math.max(0, Number(loadedPageFailure.retryCount));
            }

            const scriptHeartbeatDetail = () => {
                const session = tools.getGreetSession();
                return {
                    version: OPTIONS.scriptVersion,
                    threshold: OPTIONS.thread,
                    sessionGreetLimit: OPTIONS.sessionGreetLimit,
                    sessionGreetCount: session.count,
                    runId: session.runId,
                    localSessionRunId: session.runId,
                    backendRunId: session.backendRunId || lastBackendRunId,
                    sessionEnded: Boolean(session.ended),
                };
            };

            const setSearchAction = (action) => {
                currentSearchAction = action || (started ? '搜索/浏览职位' : '等待启动');
            };

            const getSearchAction = () => {
                if (this.pause) return '暂停中';
                return currentSearchAction || (started ? '搜索/浏览职位' : '等待启动');
            };

            const readSearchLease = () => tools.readJson(searchLeaseKey, {});

            const writeSearchLease = () => {
                hasSearchLease = true;
                tools.writeJson(searchLeaseKey, {
                    owner: PAGE_INSTANCE_ID,
                    updatedAt: Date.now(),
                    url: location.href,
                });
            };

            const acquireSearchLease = () => {
                const lease = readSearchLease();
                const expired = !lease.updatedAt || Date.now() - Number(lease.updatedAt) > OPTIONS.searchLeaseMs;
                if (lease.owner && lease.owner !== PAGE_INSTANCE_ID && !expired) {
                    hasSearchLease = false;
                    return false;
                }
                writeSearchLease();
                if (!leaseTimer) {
                    leaseTimer = setInterval(() => {
                        if (!hasSearchLease) return;
                        writeSearchLease();
                    }, Math.max(3000, Math.floor(OPTIONS.searchLeaseMs / 3)));
                }
                return true;
            };

            const releaseSearchLease = () => {
                closeActiveTempTab();
                const lease = readSearchLease();
                if (lease.owner === PAGE_INSTANCE_ID) {
                    localStorage.removeItem(searchLeaseKey);
                }
                hasSearchLease = false;
                if (leaseTimer) {
                    clearInterval(leaseTimer);
                    leaseTimer = null;
                }
            };

            const rememberTempTab = (handle) => {
                if (handle && handle !== true) {
                    activeTempTab = handle;
                }
            };

            const closeActiveTempTab = () => {
                if (activeTempTab) {
                    tools.closeTabHandle(activeTempTab);
                    activeTempTab = null;
                }
            };

            const ensureSearchLease = async (label = '运行检查') => {
                if (acquireSearchLease()) return true;
                setSearchAction('其他搜索页正在运行，本页待命');
                await api.heartbeat('search_standby', 'idle', `${label}: 其他搜索页正在运行`, {
                    ...scriptHeartbeatDetail(),
                    pageInstanceId: PAGE_INSTANCE_ID,
                    lease: readSearchLease(),
                });
                return false;
            };

            window.addEventListener('beforeunload', releaseSearchLease);

            // 日志启动/暂停事件
            const logger = new Logger(async () => {
                const res = await api.heartbeat('search', this.pause ? 'paused' : 'idle', '等待 CLI start', scriptHeartbeatDetail());
                applyBackendConfig(res.config);
                lastBackendRunId = res.run_id || lastBackendRunId;
                if (res.control === 'running' || res.should_start) {
                    if (!(await ensureSearchLease('手动启动'))) return;
                    await ensureSessionForBackendRun(lastBackendRunId, 'manual_start');
                    this.pause = false;
                    logger.setPaused(false);
                    started ? loop() : main();
                    return;
                }
                logger.setPaused(true);
                this.pause = true;
                logger.add('请回到 CLI 输入 start，确认本轮岗位标签和打招呼上限后开始');
            }, async () => {
                await api.control('pause');
                this.pause = true;
            });

            const noteBackendOffline = (message) => {
                backendOfflineFailures += 1;
                if (backendOfflineFailures >= BACKEND_OFFLINE_NOTIFY_THRESHOLD && !backendOfflineNotified) {
                    logger.add(message);
                    backendOfflineNotified = true;
                }
            };

            const noteBackendOnline = () => {
                if (backendOfflineNotified) {
                    logger.add('后端连接已恢复');
                }
                backendOfflineFailures = 0;
                backendOfflineNotified = false;
            };

            const resetProgress = () => {
                runStartedAt = nowMs();
                processedCount = 0;
                totalProcessedMs = 0;
                currentJobProgress = null;
            };

            const beginGreetSession = (reason = '') => {
                const session = tools.startGreetSession(true, lastBackendRunId);
                resetProgress();
                if (reason) {
                    logger.add(`本轮打招呼计数已重置: ${reason}`);
                }
                return session;
            };

            const ensureSessionForBackendRun = async (backendRunId, reason = '') => {
                if (!backendRunId) return tools.getGreetSession();
                const session = tools.getGreetSession();
                const legacyOrDifferentRun = !session.backendRunId || session.backendRunId !== backendRunId;
                if (!legacyOrDifferentRun && session.runId && !session.ended) {
                    return session;
                }
                const previous = { ...session };
                const next = tools.startGreetSession(true, backendRunId);
                resetProgress();
                const message = `本轮计数已按后端运行重置: ${previous.count || 0} -> 0`;
                logger.add(message);
                await api.event('session_counter_reset', message, 'script', 'info', {
                    reason: reason || 'backend_run_changed',
                    previousRunId: previous.runId || '',
                    previousBackendRunId: previous.backendRunId || '',
                    backendRunId,
                    previousCount: previous.count || 0,
                    newRunId: next.runId,
                });
                return next;
            };

            const isSessionLimitReached = () => (
                Number(OPTIONS.sessionGreetLimit) > 0
                && tools.getSessionGreetCount() >= Number(OPTIONS.sessionGreetLimit)
            );

            const stopForSessionLimit = async (count = tools.getSessionGreetCount()) => {
                const limit = Number(OPTIONS.sessionGreetLimit);
                const message = `本次打招呼上限已达: ${count}/${limit}，自动化已停止`;
                tools.endGreetSession();
                this.pause = true;
                logger.setPaused(true);
                setSearchAction(message);
                logger.add(message);
                await api.event('session_limit_reached', message, 'script', 'info', {
                    sessionGreetCount: count,
                    limit,
                    runId: tools.getGreetSession().runId,
                });
                await api.heartbeat('search', 'idle', message, scriptHeartbeatDetail());
                try {
                    await api.control('stop');
                } catch (e) {
                    await api.event('session_limit_stop_failed', `本次上限已达，但通知后端 stop 失败: ${e}`, 'script', 'error', {
                        sessionGreetCount: count,
                        limit,
                    });
                }
                lastBackendControl = 'stopped';
            };

            const ensureSessionLimitAvailable = async () => {
                if (!isSessionLimitReached()) return true;
                await stopForSessionLimit();
                return false;
            };

            const beginJobProgress = (href) => {
                currentJobProgress = {
                    href,
                    startedAt: nowMs(),
                };
            };

            const finishJobProgress = (label = '') => {
                if (!currentJobProgress) return;
                const jobMs = Math.max(0, nowMs() - currentJobProgress.startedAt);
                processedCount += 1;
                totalProcessedMs += jobMs;
                const jobSeconds = Math.round(jobMs / 1000);
                const averageSeconds = Math.round(totalProcessedMs / processedCount / 1000);
                const totalSeconds = Math.round((nowMs() - (runStartedAt || currentJobProgress.startedAt)) / 1000);
                const remaining = jobHrefs.length;
                const total = processedCount + remaining;
                const suffix = label ? `，${label}` : '';
                logger.add(`[进度] 已处理 ${processedCount}/${total}，剩余 ${remaining}，本岗位 ${jobSeconds}s，平均 ${averageSeconds}s，累计 ${convertTime(totalSeconds)}${suffix}`);
                currentJobProgress = null;
            };

            const syncControlFromBackend = async (action = '') => {
                const res = await api.heartbeat(
                    'search',
                    this.pause ? 'paused' : 'running',
                    action || getSearchAction(),
                    scriptHeartbeatDetail()
                );
                applyBackendConfig(res.config);
                lastBackendRunId = res.run_id || lastBackendRunId;
                const previousControl = lastBackendControl;
                lastBackendControl = res.control || lastBackendControl;
                if (res.offline) {
                    noteBackendOffline('后端未连接：请确认 python main.py 正在运行，端口为 33333，并重新保存油猴脚本权限');
                    logger.setPaused(true);
                    this.pause = true;
                    return false;
                }
                noteBackendOnline();
                if (res.should_stop || res.control === 'stopped') {
                    if (!this.pause) logger.add('CLI 已停止自动化');
                    tools.endGreetSession();
                    releaseSearchLease();
                    logger.setPaused(true);
                    this.pause = true;
                    return false;
                }
                if (res.should_pause || res.control === 'paused') {
                    if (!this.pause) logger.add('CLI 已暂停自动化');
                    releaseSearchLease();
                    logger.setPaused(true);
                    this.pause = true;
                    return false;
                }
                if (res.should_start || res.control === 'running') {
                    await ensureSessionForBackendRun(lastBackendRunId, previousControl === 'stopped' ? 'stopped_to_running' : 'backend_running');
                    const session = tools.getGreetSession();
                    if (!session.runId || session.ended || previousControl === 'stopped') {
                        beginGreetSession(previousControl === 'stopped' ? '停止后重新开始' : '开始新一轮');
                    }
                    if (this.pause) logger.add('CLI 已允许开始/继续运行');
                    logger.setPaused(false);
                    this.pause = false;
                    return true;
                }
                return !this.pause;
            };

            setInterval(async () => {
                if (await syncControlFromBackend()) {
                    if (!(await ensureSearchLease('定时运行检查'))) return;
                    if (!started && !booting) {
                        main();
                    } else if (started && !booting && !waitingForGreeting) {
                        loop();
                    }
                }
            }, 3000);

            const startGreetingWait = (jobInfo, href, requestId, attempt = 1) => {
                waitingForGreeting = true;
                activeGreetingJob = {
                    jobInfo,
                    href,
                    requestId,
                    attempt: Math.max(1, Number(attempt || 1)),
                    maxAttempts: Math.max(1, Number(OPTIONS.greetMaxAttempts || 3)),
                };
                if (greetTimeoutId) clearTimeout(greetTimeoutId);
                greetTimeoutId = setTimeout(async () => {
                    if (!waitingForGreeting) return;
                    await handleGreetingResult({
                        success: false,
                        error: 'greet_window_timeout',
                        failureCode: 'greet_timeout',
                        retryable: true,
                        requestId,
                    });
                    return;
                }, 60000);
            };

            const finishGreetingWait = (requestId = '') => {
                waitingForGreeting = false;
                if (greetTimeoutId) {
                    clearTimeout(greetTimeoutId);
                    greetTimeoutId = null;
                }
                closeActiveTempTab();
                tools.clearGreetContext(requestId);
                activeGreetingJob = null;
            };

            const isNonRetryableGreetingError = (error) => {
                const text = String(error || '');
                return tools.isPlatformLimitError(text)
                    || tools.isManualInterruptionError(text)
                    || text.includes('未启用打招呼用语')
                    || text.includes('缺少聊天页地址')
                    || text.includes('缺少打招呼')
                    || text.includes('浏览器拦截');
            };

            const handleGreetingResult = async (data = {}) => {
                const active = activeGreetingJob || {};
                const requestId = data.greetRequestId || data.requestId || active.requestId || '';
                if (active.requestId && requestId && requestId !== active.requestId) {
                    await api.event('greet_result_stale', `忽略过期打招呼结果: ${requestId}`, 'script', 'info', {
                        activeRequestId: active.requestId,
                        requestId,
                    });
                    return;
                }

                const jobInfo = active.jobInfo || {};
                const href = active.href || jobInfo.url || '';
                const attempt = Math.max(1, Number(data.attempt || active.attempt || 1));
                const maxAttempts = Math.max(1, Number(active.maxAttempts || OPTIONS.greetMaxAttempts || 3));
                const error = String(data.error || data.failureCode || 'greet_failed');

                if (data.success) {
                    const count = Number(data.sessionGreetCount || tools.getSessionGreetCount());
                    logger.add(`打招呼成功，本轮计数 ${count}/${OPTIONS.sessionGreetLimit}`);
                    finishGreetingWait(requestId);
                    finishJobProgress('打招呼成功');
                    if (isSessionLimitReached()) {
                        await stopForSessionLimit(Number(data.sessionGreetCount || tools.getSessionGreetCount()));
                        return;
                    }
                    loop();
                    return;
                }

                const retryable = data.retryable !== false && !isNonRetryableGreetingError(error);
                const canRetry = retryable && jobInfo && jobInfo.chatUrl && attempt < maxAttempts;
                logger.add(`打招呼失败 ${attempt}/${maxAttempts}${error ? ': ' + error : ''}`);

                if (tools.isPlatformLimitError(error)) {
                    finishGreetingWait(requestId);
                    finishJobProgress('平台限制');
                    await handlePageFailure(tools.platformLimitReason(error), 'platform_limit', 'chat_greet');
                    return;
                }
                if (tools.isManualInterruptionError(error)) {
                    finishGreetingWait(requestId);
                    finishJobProgress('需要人工处理');
                    await handleManualInterruption(tools.manualInterruptionReason(error), 'chat_greet');
                    return;
                }

                if (canRetry) {
                    const nextAttempt = attempt + 1;
                    const delay = Number((OPTIONS.greetRetryDelays || [0, 3000, 8000])[nextAttempt - 1] || 3000);
                    finishGreetingWait(requestId);
                    logger.add(`准备第 ${nextAttempt}/${maxAttempts} 次打招呼重试: ${jobInfo.title || ''}`);
                    await api.event('greet_retry_scheduled', `准备第 ${nextAttempt}/${maxAttempts} 次打招呼重试: ${jobInfo.title || ''}`, 'script', 'warning', {
                        title: jobInfo.title || '',
                        error,
                        attempt,
                        nextAttempt,
                        maxAttempts,
                        requestId,
                    });
                    setTimeout(() => {
                        openGreetingChat(jobInfo, href, `retry_after_${error}`, nextAttempt).catch(async (retryError) => {
                            await handleGreetingResult({
                                success: false,
                                error: String(retryError),
                                failureCode: 'greet_retry_open_failed',
                                retryable: !isNonRetryableGreetingError(retryError),
                                attempt: nextAttempt,
                            });
                        });
                    }, delay);
                    return;
                }

                finishGreetingWait(requestId);
                await api.event('greet_failed_final', `打招呼最终失败: ${jobInfo.title || ''} / ${error}`, 'script', 'error', {
                    title: jobInfo.title || '',
                    error,
                    attempt,
                    maxAttempts,
                    requestId,
                });
                finishJobProgress('打招呼最终失败');
                loop();
            };

            const resetManualInterventionRecovery = async (label = '') => {
                if (manualInterventionRetryCount <= 0 && !localStorage.getItem(manualRecoveryStateKey)) return;
                const previousCount = manualInterventionRetryCount;
                manualInterventionRetryCount = 0;
                clearManualRecoveryState();
                await api.event('manual_intervention_recovery_success', label || '人工校验恢复成功，已回到正常流程', 'script', 'info', {
                    previousCount,
                });
            };

            const resetPageFailureRecovery = async (label = '') => {
                if (pageFailureRetryCount <= 0 && !localStorage.getItem(pageFailureStateKey)) return;
                const previousCount = pageFailureRetryCount;
                pageFailureRetryCount = 0;
                clearPageFailureState();
                await api.event('page_failure_recovery_success', label || '页面失败恢复成功，已回到正常流程', 'script', 'info', {
                    previousCount,
                });
            };

            const handlePageFailure = async (reason, kind = 'element_retry', sourcePage = 'search') => {
                const finalReason = reason || '未知页面失败';
                const isPlatformLimit = kind === 'platform_limit';
                const retryEvent = isPlatformLimit ? 'platform_limit_retry' : 'element_retry';
                const pauseEvent = isPlatformLimit ? 'platform_limit_pause' : 'element_retry_pause';
                pageFailureRetryCount += 1;
                jobHrefs = [];
                elsLen = 0;
                page = 0;
                lastJobListEventKey = '';
                if (currentJobProgress) {
                    finishJobProgress(isPlatformLimit ? '平台限制恢复' : '元素缺失恢复');
                }

                if (pageFailureRetryCount <= 3) {
                    const message = `${isPlatformLimit ? '平台次数限制' : '页面元素缺失'}: ${finalReason}，刷新搜索页重试 ${pageFailureRetryCount}/3`;
                    logger.add(message);
                    setSearchAction(message);
                    savePageFailureState({
                        retryCount: pageFailureRetryCount,
                        kind,
                        reason: finalReason,
                    });
                    await api.event(retryEvent, message, 'script', isPlatformLimit ? 'error' : 'info', {
                        reason: finalReason,
                        retryCount: pageFailureRetryCount,
                        maxRetries: 3,
                        sourcePage,
                    });
                    await api.heartbeat('search', 'running', message, {
                        ...scriptHeartbeatDetail(),
                        reason: finalReason,
                        retryCount: pageFailureRetryCount,
                        maxRetries: 3,
                        sourcePage,
                    });
                    tools.openTabNSetTimestamp(SEARCHPATH.zhipin, this.targets.search, true);
                    return true;
                }

                const message = `${isPlatformLimit ? '平台次数限制' : '页面元素缺失'}连续 3 次恢复失败，已暂停: ${finalReason}`;
                pageFailureRetryCount = 0;
                clearPageFailureState();
                this.pause = true;
                logger.setPaused(true);
                logger.add(message);
                setSearchAction(message);
                await api.event(pauseEvent, message, 'script', 'error', {
                    reason: finalReason,
                    maxRetries: 3,
                    sourcePage,
                });
                await api.heartbeat('search', 'error', message, {
                    ...scriptHeartbeatDetail(),
                    reason: finalReason,
                    maxRetries: 3,
                    sourcePage,
                });
                try {
                    await api.control('pause');
                } catch (e) {
                    await api.event('page_failure_pause_failed', `页面失败暂停通知失败: ${e}`, 'script', 'error', {
                        reason: finalReason,
                        kind,
                    });
                }
                lastBackendControl = 'paused';
                return false;
            };

            const handleManualInterruption = async (reason, sourcePage = 'search') => {
                const finalReason = reason || '未知人工校验';
                manualInterventionRetryCount += 1;
                jobHrefs = [];
                elsLen = 0;
                page = 0;
                lastJobListEventKey = '';
                if (currentJobProgress) {
                    finishJobProgress('人工校验恢复');
                }

                if (manualInterventionRetryCount <= OPTIONS.manualInterventionMaxRetries) {
                    const nextTagIdx = this.tags.length ? (currentTagIdx + 1) % this.tags.length : currentTagIdx;
                    const nextKeyword = this.tags[nextTagIdx] || '';
                    const message = `需要人工校验: ${finalReason}，尝试切换关键词恢复 ${manualInterventionRetryCount}/${OPTIONS.manualInterventionMaxRetries}`;
                    logger.add(message);
                    setSearchAction(message);
                    saveManualRecoveryState({
                        retryCount: manualInterventionRetryCount,
                        nextTagIdx,
                        reason: finalReason,
                    });
                    await api.event('manual_intervention_recovery_attempt', message, 'script', 'info', {
                        reason: finalReason,
                        retryCount: manualInterventionRetryCount,
                        maxRetries: OPTIONS.manualInterventionMaxRetries,
                        nextKeyword,
                        nextTagIdx,
                        sourcePage,
                    });
                    await api.heartbeat('search', 'running', message, {
                        ...scriptHeartbeatDetail(),
                        reason: finalReason,
                        retryCount: manualInterventionRetryCount,
                        maxRetries: OPTIONS.manualInterventionMaxRetries,
                        nextKeyword,
                        sourcePage,
                    });
                    currentTagIdx = nextTagIdx;
                    tools.openTabNSetTimestamp(SEARCHPATH.zhipin, this.targets.search, true);
                    return true;
                }

                const message = `连续 ${OPTIONS.manualInterventionMaxRetries} 次恢复失败，已暂停，请人工处理 BOSS 页面验证: ${finalReason}`;
                manualInterventionRetryCount = 0;
                clearManualRecoveryState();
                this.pause = true;
                logger.setPaused(true);
                logger.add(message);
                setSearchAction(message);
                await api.event('manual_intervention_recovery_failed', message, 'script', 'error', {
                    reason: finalReason,
                    maxRetries: OPTIONS.manualInterventionMaxRetries,
                    sourcePage,
                });
                await api.event('manual_intervention_required', message, 'script', 'error', { reason: finalReason });
                await api.heartbeat('search', 'error', message, {
                    ...scriptHeartbeatDetail(),
                    reason: finalReason,
                    maxRetries: OPTIONS.manualInterventionMaxRetries,
                    sourcePage,
                });
                try {
                    await api.control('pause');
                } catch (e) {
                    await api.event('manual_intervention_pause_failed', `人工校验暂停通知失败: ${e}`, 'script', 'error', {
                        reason: finalReason,
                    });
                }
                lastBackendControl = 'paused';
                return false;
            };

            // 开始广播
            const startBroadcast = () => {
                this.__broadcast(this.targets.search);
                // 接收聊天页的消息提醒
                this.broadcast.on(this.bcTypes.STATUS, (from, data) => {
                    if (from === this.targets.chat) {
                        logger.add(data);
                    }
                });
                // 发送自我介绍
                this.broadcast.on(this.bcTypes.INTRODUCE, (from, data) => {
                    this.broadcast.reply(
                        from,
                        this.bcTypes.INTRODUCE,
                        { introduce: this.introduce },
                        data.requestId,
                        data.responseType
                    );
                });
                // 分割线
                this.broadcast.on(this.bcTypes.DIVIDER, () => {
                    logger.divider();
                });
                // 监听打招呼
                greetListener();
                // 监听聊天页
                // 心跳监听
                heartBeatListener();
            };

            // 执行搜索
            const search = async (kw) => {
                try {
                    setSearchAction(`搜索关键词: ${kw}`);
                    const platformLimit = tools.detectPlatformLimit();
                    if (platformLimit) {
                        throw new Error(`平台次数限制: ${platformLimit}`);
                    }
                    const interruption = tools.detectManualInterruption();
                    if (interruption) {
                        throw new Error(`需要人工处理: ${interruption}`);
                    }
                    await api.event('search_started', `开始搜索关键词: ${kw}`, 'script', 'info', { keyword: kw });
                    const input = await tools.endlessFind(SELECTORS.ZHIPIN.SEARCH.SEARCHINPUT);
                    const btn = await tools.endlessFind(SELECTORS.ZHIPIN.SEARCH.SEARCHBTN);
                    tools.inputText(input, kw);
                    btn.click();
                    await api.event('search_finished', `搜索已提交: ${kw}`, 'script', 'info', { keyword: kw });
                } catch (e) {
                    if (tools.isManualInterruptionError(e)) throw e;
                    if (tools.isPlatformLimitError(e)) throw e;
                    logger.add('搜索出错');
                    await api.event('search_failed', `搜索出错: ${e}`, 'script', 'error', { keyword: kw });
                    throw new Error('搜索出错');
                }
            };

            // 获取职位链接
            const getJobHrefs = async () => {
                try {
                    setSearchAction('读取职位列表');
                    const platformLimit = tools.detectPlatformLimit();
                    if (platformLimit) {
                        throw new Error(`平台次数限制: ${platformLimit}`);
                    }
                    const interruption = tools.detectManualInterruption();
                    if (interruption) {
                        throw new Error(`需要人工处理: ${interruption}`);
                    }
                    const jobUl = await tools.waitForOne(SELECTORS.ZHIPIN.SEARCH.JOBLIST_CANDIDATES, 15000);
                    const collect = () => {
                        let aList = [];
                        for (const selector of SELECTORS.ZHIPIN.SEARCH.JOBHREFS_CANDIDATES) {
                            aList = Array.from(jobUl.querySelectorAll(selector));
                            if (aList.length) break;
                        }
                        if (!aList.length) {
                            aList = Array.from(document.querySelectorAll('a[href*="/job_detail/"]'));
                        }
                        return Array.from(
                            new Set(Array.from(aList).map(a => tools.hrefFromJobNode(a)).filter(Boolean))
                        );
                    };
                    let hrefs = collect();
                    let newHrefs = hrefs.filter(href => !seenJobHrefs.has(href) && !backendProcessedHrefs.has(href));
                    const startedAt = Date.now();
                    while (!newHrefs.length && hrefs.length <= elsLen && Date.now() - startedAt < 5000) {
                        await tools.asyncSleep(500);
                        hrefs = collect();
                        newHrefs = hrefs.filter(href => !seenJobHrefs.has(href) && !backendProcessedHrefs.has(href));
                    }
                    const eventKey = `${hrefs.length}:${newHrefs.length}:${hrefs[hrefs.length - 1] || ''}`;
                    if (eventKey !== lastJobListEventKey) {
                        lastJobListEventKey = eventKey;
                        await api.event('job_list_found', `发现职位链接 ${hrefs.length} 个，新职位 ${newHrefs.length} 个`, 'script', 'info', { count: hrefs.length, newCount: newHrefs.length });
                    }
                    return [newHrefs, hrefs];
                } catch (e) {
                    if (tools.isManualInterruptionError(e)) throw e;
                    if (tools.isPlatformLimitError(e)) throw e;
                    logger.add('获取职位链接出错');
                    await api.event('job_list_failed', `获取职位链接出错: ${e}`, 'script', 'error');
                    throw new Error('获取职位链接出错');
                }
            };

            // 读取当前关键词的职位。没有新职位时不滚动，直接切换关键词。
            const nextPage = async () => {
                let hrefs;
                [jobHrefs, hrefs] = await getJobHrefs();
                elsLen = hrefs.length;
                await resetManualInterventionRecovery('人工校验恢复成功，已读取到正常职位列表');
                await resetPageFailureRecovery('页面失败恢复成功，已读取到正常职位列表');
                if (jobHrefs.length > 0) {
                    page++;
                    logger.add(`开始浏览第 ${page} 批`);
                    return true;
                }
                const keyword = this.tags[currentTagIdx] || '';
                logger.add(`当前关键词没有新职位: ${keyword || '-'}`);
                await api.event('job_list_empty', `当前关键词没有新职位: ${keyword || '-'}`, 'script', 'info', {
                    page,
                    keyword,
                    knownCount: elsLen,
                });
                return false;
            };

            document.nextPage = nextPage;

            const switchToNextKeyword = async (reason = '') => {
                if (!this.tags.length) return false;
                const total = this.tags.length;
                for (let attempt = 0; attempt < total; attempt++) {
                    currentTagIdx = (currentTagIdx + 1) % total;
                    jobHrefs = [];
                    elsLen = 0;
                    page = 0;
                    lastJobListEventKey = '';
                    const keyword = this.tags[currentTagIdx];
                    const suffix = reason ? `（${reason}）` : '';
                    logger.add(`切换搜索关键词: ${keyword}${suffix}`);
                    await api.event('keyword_switched', `切换搜索关键词: ${keyword}`, 'script', 'info', {
                        keyword,
                        index: currentTagIdx,
                        wrapped: currentTagIdx === 0,
                        reason,
                    });
                    setSearchAction(`搜索关键词: ${keyword}`);
                    await search(keyword);
                    await tools.actionSleep(1500);
                    if (await nextPage()) {
                        return true;
                    }
                }
                logger.add('所有关键词本轮未发现新职位，稍后从第一个关键词重新开始');
                await api.event('all_keywords_no_new_jobs', '所有关键词本轮未发现新职位，稍后从第一个关键词重新开始', 'script', 'info', {
                    tags: this.tags,
                    seenCount: seenJobHrefs.size,
                    reason,
                });
                return false;
            };

            const extractJobInfoFromDocument = (doc, href, source = 'document') => {
                const chatBtn = tools.findOne(SELECTORS.ZHIPIN.DETAIL.STARTCHAT, doc);
                const title = tools.textOf(SELECTORS.ZHIPIN.DETAIL.JOBNAME_CANDIDATES, doc);
                const salary = tools.textOf(SELECTORS.ZHIPIN.DETAIL.SALARY_CANDIDATES, doc);
                const detail = tools.textOf(SELECTORS.ZHIPIN.DETAIL.DETAIL_CANDIDATES, doc);
                const company = tools.textOf(SELECTORS.ZHIPIN.DETAIL.COMPANY_CANDIDATES, doc);
                const city = tools.textOf(SELECTORS.ZHIPIN.DETAIL.CITY_CANDIDATES, doc);
                const chatUrl = chatBtn && (chatBtn.getAttribute(SELECTORS.ZHIPIN.DETAIL.CHATURL) || chatBtn.getAttribute('href') || chatBtn.dataset.redirectUrl);
                const addUrl = chatBtn && (chatBtn.dataset.url || chatBtn.getAttribute('data-url') || chatBtn.getAttribute('href'));
                const talkedReason = tools.contactedReasonFromElement(chatBtn);
                return {
                    title,
                    salary,
                    detail,
                    company,
                    city,
                    chatUrl: tools.normalUrl(chatUrl),
                    addUrl: tools.normalUrl(addUrl),
                    talked: Boolean(talkedReason),
                    talked_reason: talkedReason,
                    url: href,
                    source,
                };
            };

            const fetchJobInfoFallback = async (href, originalError) => {
                await api.event('job_detail_fetch_fallback_started', `尝试直接解析详情页: ${href}`, 'script', 'info', { url: href, originalError: String(originalError) });
                try {
                    const resp = await fetch(href, { credentials: 'include' });
                    if (!resp.ok) throw new Error(`详情页请求失败: ${resp.status}`);
                    const html = await resp.text();
                    const doc = new DOMParser().parseFromString(html, 'text/html');
                    const interruptionText = doc.body ? doc.body.innerText : '';
                    const platformLimit = tools.detectPlatformLimitText(interruptionText);
                    if (platformLimit) throw new Error(`平台次数限制: ${platformLimit}`);
                    const interruption = tools.detectInterruptionText(interruptionText);
                    if (interruption) throw new Error(`需要人工处理: ${interruption}`);
                    const info = extractJobInfoFromDocument(doc, href, 'fetch_fallback');
                    if (!info.title || !info.detail) throw new Error('详情页 fetch 兜底解析失败：缺少标题或描述');
                    await api.event('job_detail_fetch_fallback_finished', `详情页兜底解析成功: ${info.title}`, 'script', 'info', {
                        url: href,
                        hasAddUrl: Boolean(info.addUrl),
                        hasChatUrl: Boolean(info.chatUrl),
                    });
                    return info;
                } catch (fallbackError) {
                    if (tools.isPlatformLimitError(fallbackError)) {
                        await api.event('job_detail_platform_limit', `详情页触发平台次数限制: ${fallbackError}`, 'script', 'error', { url: href, originalError: String(originalError) });
                        throw fallbackError;
                    }
                    if (tools.isManualInterruptionError(fallbackError)) {
                        await api.event('job_detail_manual_intervention', `详情页需要人工校验: ${fallbackError}`, 'script', 'error', { url: href, originalError: String(originalError) });
                        throw fallbackError;
                    }
                    await api.event('job_detail_fetch_fallback_failed', `详情页兜底解析失败: ${fallbackError}`, 'script', 'error', { url: href, originalError: String(originalError) });
                    throw new Error(`详情页广播失败且兜底解析失败: ${originalError}; ${fallbackError}`);
                }
            };

            // 获取职位信息
            const getJobInfo = async (href) => {
                const platformLimit = tools.detectPlatformLimit();
                if (platformLimit) throw new Error(`平台次数限制: ${platformLimit}`);
                const interruption = tools.detectManualInterruption();
                if (interruption) throw new Error(`需要人工处理: ${interruption}`);
                setSearchAction(`打开职位详情: ${href}`);
                await api.event('job_detail_opened', `打开职位详情: ${href}`, 'script', 'info', { url: href });
                const detailResponse = this.broadcast.receive(this.targets.detail, this.bcTypes.GET_JOB_INFO, OPTIONS.jobInfoResponseTimeout);
                const opened = tools.openTabNSetTimestamp(href, this.targets.detail);
                rememberTempTab(opened);
                setSearchAction(`等待详情页回传职位信息: ${href}`);
                await api.heartbeat('search', 'running', `等待详情页回传职位信息: ${href}`, {
                    ...scriptHeartbeatDetail(),
                    url: href,
                    detailWindowOpened: Boolean(opened),
                    jobInfoResponseTimeout: OPTIONS.jobInfoResponseTimeout,
                });
                let info;
                if (!opened) {
                    detailResponse.catch(() => null);
                    const popupError = new Error('浏览器拦截了职位详情页弹窗');
                    await api.event('job_detail_popup_blocked', `${popupError.message}: ${href}`, 'script', 'error', { url: href });
                    info = await fetchJobInfoFallback(href, popupError);
                } else {
                    try {
                        info = await detailResponse;
                    } catch (e) {
                        if (tools.isManualInterruptionError(e)) throw e;
                        if (tools.isPlatformLimitError(e)) throw e;
                        await api.event('job_detail_timeout', `详情页未回传职位信息: ${href}`, 'script', 'error', { url: href, error: String(e) });
                        info = await fetchJobInfoFallback(href, e);
                    }
                }
                if (info && info.manual_intervention) throw new Error(`需要人工处理: ${info.reason || info.error || '详情页人工校验'}`);
                if (info && info.page_failure) throw new Error(`${info.failure_kind === 'platform_limit' ? '平台次数限制' : '未找到目标元素'}: ${info.reason || info.error || '详情页页面失败'}`);
                if (!info || !info.title || !info.detail) throw new Error('职位详情缺少标题或描述');
                closeActiveTempTab();
                await api.event('job_detail_received', `已读取职位详情: ${info.title}`, 'script', 'info', info);
                return info;
            };


            const getJobInfoWithRetry = async (href) => {
                try {
                    return await getJobInfo(href);
                } catch (firstError) {
                    closeActiveTempTab();
                    if (tools.isPlatformLimitError(firstError) || tools.isElementMissingError(firstError)) {
                        await api.event(
                            tools.isPlatformLimitError(firstError) ? 'job_detail_platform_limit' : 'job_detail_element_missing',
                            `职位详情读取触发页面恢复: ${href}`,
                            'script',
                            'error',
                            { url: href, error: String(firstError) }
                        );
                        throw firstError;
                    }
                    if (tools.isManualInterruptionError(firstError)) {
                        await api.event('job_detail_manual_intervention', `职位详情触发人工校验，切换关键词恢复: ${href}`, 'script', 'error', {
                            url: href,
                            error: String(firstError),
                        });
                        throw firstError;
                    }
                    await api.event('job_detail_failed', `职位详情读取失败，准备重试一次: ${href}`, 'script', 'error', {
                        url: href,
                        error: String(firstError),
                    });
                    await tools.actionSleep(1000);
                    try {
                        return await getJobInfo(href);
                    } catch (secondError) {
                        closeActiveTempTab();
                        if (tools.isPlatformLimitError(secondError) || tools.isElementMissingError(secondError)) {
                            await api.event(
                                tools.isPlatformLimitError(secondError) ? 'job_detail_platform_limit' : 'job_detail_element_missing',
                                `职位详情重试触发页面恢复: ${href}`,
                                'script',
                                'error',
                                { url: href, firstError: String(firstError), secondError: String(secondError) }
                            );
                            throw secondError;
                        }
                        if (tools.isManualInterruptionError(secondError)) {
                            await api.event('job_detail_manual_intervention', `职位详情重试触发人工校验，切换关键词恢复: ${href}`, 'script', 'error', {
                                url: href,
                                firstError: String(firstError),
                                secondError: String(secondError),
                            });
                            throw secondError;
                        }
                        await api.event('job_detail_failed', `职位详情读取重试失败，跳过职位: ${href}`, 'script', 'error', {
                            url: href,
                            firstError: String(firstError),
                            secondError: String(secondError),
                        });
                        throw secondError;
                    }
                }
            };

            // 添加到聊天列表
            const addToChatList = async (url) => {
                if (!url) throw new Error('缺少打招呼请求链接');
                try {
                    await api.event('chat_entry_request_started', `请求打招呼入口: ${url}`, 'script', 'info', { url });
                    const resp = await fetch(url, { credentials: 'include' });
                    if (!(resp.ok && resp.status === 200)) {
                        throw new Error(`BOSS 网络响应异常: ${resp.status}`);
                    }
                    const data = await resp.json();
                    if (data.code === 0) {
                        await api.event('chat_entry_request_finished', '打招呼入口请求成功', 'script', 'info', {
                            hasRedirect: Boolean(tools.findChatUrlDeep(data)),
                        });
                        return data;
                    }
                    const msg = data?.zpData?.bizData?.chatRemindDialog?.title || data?.message || JSON.stringify(data).slice(0, 120);
                    throw new Error(msg || 'BOSS 拒绝打招呼入口请求');
                } catch (e) {
                    logger.add(`打招呼入口失败: ${e}`);
                    throw e;
                }
            };

            const openGreetingChat = async (jobInfo, href, reason, attempt = 1) => {
                if (!jobInfo.chatUrl) throw new Error('缺少聊天页地址');
                const requestId = tools.newGreetRequestId();
                startGreetingWait(jobInfo, href, requestId, attempt);
                tools.saveGreetContext({
                    requestId,
                    url: href,
                    chatUrl: jobInfo.chatUrl || '',
                    title: jobInfo.title,
                    company: jobInfo.company || '',
                    salary: jobInfo.salary || '',
                    greeting: this.introduce,
                    reason,
                    attempt,
                    maxAttempts: OPTIONS.greetMaxAttempts,
                    createdAt: Date.now(),
                });
                await api.event('greet_chat_opened', `打开聊天页准备打招呼 ${attempt}/${OPTIONS.greetMaxAttempts}: ${jobInfo.title}`, 'script', 'info', {
                    title: jobInfo.title,
                    chatUrl: jobInfo.chatUrl,
                    reason,
                    requestId,
                    attempt,
                    maxAttempts: OPTIONS.greetMaxAttempts,
                });
                const opened = tools.openTabNSetTimestamp(jobInfo.chatUrl, this.targets.chatGreet, false, {
                    force: Number(attempt) > 1,
                    cooldownMs: Number(attempt) > 1 ? 0 : OPTIONS.openCooldownMs,
                });
                rememberTempTab(opened);
                if (!opened) {
                    finishGreetingWait(requestId);
                    throw new Error('浏览器拦截了聊天页弹窗，请允许 zhipin.com 弹出窗口后重试');
                }
            };

            const buildGreetingPayload = (jobInfo, analysis, href, reason = '') => ({
                reason,
                score: analysis.total_score,
                threshold: OPTIONS.thread,
                recommendation: analysis.recommendation || '',
                risks: analysis.risks || [],
                greeting: this.introduce,
                job: {
                    url: href,
                    title: jobInfo.title || '',
                    company: jobInfo.company || '',
                    salary: jobInfo.salary || '',
                    city: jobInfo.city || '',
                },
            });

            const recordGreetingSuggestion = async (jobInfo, analysis, href, reason) => {
                await api.createAction(
                    'greet_suggestion',
                    buildGreetingPayload(jobInfo, analysis, href, reason),
                    jobInfo,
                    'completed'
                );
                logger.add(`${reason}: ${jobInfo.title}`);
                await api.event('greet_suggestion', `${reason}: ${jobInfo.title}`, 'script', 'info', { title: jobInfo.title, score: analysis.total_score });
            };

            const sendGreetingFromSearch = async (jobInfo, href) => {
                logger.add(`正在给职位 [${jobInfo.title}] 发送打招呼消息`);
                await api.event('greet_started', `准备打招呼: ${jobInfo.title}`, 'script', 'info', { title: jobInfo.title, score: jobInfo.score });
                if (!jobInfo.addUrl && !jobInfo.chatUrl) {
                    await api.createAction('greet_unavailable', {
                        reason: '缺少打招呼链接',
                        source: jobInfo.source || 'detail',
                        hasAddUrl: Boolean(jobInfo.addUrl),
                        hasChatUrl: Boolean(jobInfo.chatUrl),
                    }, jobInfo, 'completed');
                    await api.event('greet_failed', `缺少打招呼链接: ${jobInfo.title}`, 'script', 'error', { title: jobInfo.title, source: jobInfo.source || 'detail' });
                    finishJobProgress('缺少打招呼入口');
                    setTimeout(loop, 0);
                    return;
                }
                if (jobInfo.talked) {
                    const reason = jobInfo.talked_reason || '页面显示已沟通';
                    logger.add(`职位 [${jobInfo.title}] ${reason}，跳过打招呼`);
                    await api.createAction('already_contacted', { reason }, jobInfo, 'completed');
                    await api.event('already_contacted', `${reason}: ${jobInfo.title}`, 'script', 'info', { title: jobInfo.title, url: href, reason });
                    finishJobProgress('已沟通跳过');
                    setTimeout(loop, 0);
                    return;
                }
                try {
                    await tools.actionSleep();
                    if (tools.isChatUrl(jobInfo.addUrl)) {
                        jobInfo.chatUrl = jobInfo.addUrl;
                        await api.event('greet_entry_skipped', '打招呼入口本身是聊天页，直接打开聊天页', 'script', 'info', { title: jobInfo.title, chatUrl: jobInfo.chatUrl });
                    } else if (jobInfo.addUrl) {
                        const entryResult = await addToChatList(jobInfo.addUrl);
                        const redirectedChatUrl = tools.findChatUrlDeep(entryResult);
                        if (redirectedChatUrl) jobInfo.chatUrl = redirectedChatUrl;
                    } else {
                        await api.event('greet_entry_skipped', '详情页没有独立打招呼入口，直接打开聊天页', 'script', 'info', { title: jobInfo.title, chatUrl: jobInfo.chatUrl });
                    }
                    await openGreetingChat(jobInfo, href, '入口请求成功或已有聊天页地址');
                } catch (e) {
                    if (tools.isPlatformLimitError(e)) {
                        finishGreetingWait();
                        await handlePageFailure(tools.platformLimitReason(e), 'platform_limit', 'chat_greet');
                        return;
                    }
                    if (tools.isElementMissingError(e)) {
                        finishGreetingWait();
                        await handlePageFailure(String(e), 'element_retry', 'chat_greet');
                        return;
                    }
                    if (tools.isManualInterruptionError(e)) {
                        finishGreetingWait();
                        await handleManualInterruption(tools.manualInterruptionReason(e), 'chat_greet');
                        return;
                    }
                    if (jobInfo.chatUrl) {
                        logger.add(`入口请求失败，尝试直接打开聊天页: ${jobInfo.chatUrl}`);
                        await api.event('greet_entry_fallback', `入口请求失败，尝试直接打开聊天页: ${e}`, 'script', 'info', { title: jobInfo.title, chatUrl: jobInfo.chatUrl });
                        try {
                            await openGreetingChat(jobInfo, href, '入口请求失败后的聊天页兜底');
                            return;
                        } catch (fallbackError) {
                            finishGreetingWait();
                            await api.event('greet_failed', `聊天页兜底失败: ${fallbackError}`, 'script', 'error', { title: jobInfo.title });
                        }
                    } else {
                        finishGreetingWait();
                        await api.event('greet_failed', `打招呼入口失败且无聊天页兜底: ${e}`, 'script', 'error', { title: jobInfo.title });
                    }
                    finishJobProgress('打招呼失败');
                    setTimeout(loop, 0);
                }
            };

            // 打招呼监听
            const greetListener = () => {
                this.broadcast.on(this.bcTypes.SAY_HI, async (from, data) => {
                    if (from !== this.targets.chatGreet) return;
                    // 需要自我介绍
                    if (data.requestId) {
                        this.broadcast.reply(
                            from,
                            this.bcTypes.SAY_HI,
                            { introduce: this.introduce },
                            data.requestId,
                            data.responseType
                        );
                        return;
                    }
                    // 鍛婄煡缁撴灉
                    await handleGreetingResult(data || {});
                    return;
                });
            };

            const sendBroadcastSafe = (to, type, data = null) => {
                if (!this.broadcast) return;
                this.broadcast.send(to, type, data).catch((e) => {
                    api.event('broadcast_send_failed', `广播发送失败: ${type} / ${e}`, 'script', 'error', {
                        to,
                        type,
                    }).catch(() => null);
                });
            };


            // 心跳监听
            const heartBeatListener = () => {
                this.broadcast.on(this.bcTypes.HEART_BEAT, async (from, data) => {
                    this.broadcast.reply(
                        from,
                        this.bcTypes.HEART_BEAT,
                        { success: true },
                        data.requestId,
                        data.responseType
                    );
                });
            }

            // 寰幆
            const loop = async () => {
                if (loopRunning) return;
                loopRunning = true;
                try {
                    if (!(await ensureSearchLease('循环运行'))) return;
                    if (waitingForGreeting) return;
                    const platformLimit = tools.detectPlatformLimit();
                    if (platformLimit) {
                        await handlePageFailure(platformLimit, 'platform_limit', 'search');
                        return;
                    }
                    const interruption = tools.detectManualInterruption();
                    if (interruption) {
                        await handleManualInterruption(interruption, 'search');
                        return;
                    }
                    if (this.pause) {
                        logger.add('暂停中...');
                        return;
                    }
                    if (!(await ensureSessionLimitAvailable())) return;
                    logger.divider();

                    if (jobHrefs.length === 0) {
                        const hasNext = await nextPage();
                        if (hasNext) {
                            setTimeout(loop, 0);
                            return;
                        }
                        const hasNextKeyword = await switchToNextKeyword('当前关键词没有更多职位');
                        if (hasNextKeyword) {
                            setTimeout(loop, 0);
                            return;
                        }
                        await api.heartbeat('search', 'running', '所有关键词暂无新职位，稍后重新轮询');
                        setTimeout(loop, OPTIONS.actionDelayMs);
                        return;
                    }

                    const href = jobHrefs.shift();
                    seenJobHrefs.add(href);
                    beginJobProgress(href);
                    logger.add('正在获取职位详情');
                    setSearchAction(`获取职位详情: ${href}`);
                    const jobInfo = await getJobInfoWithRetry(href);
                    jobInfo.url = href;

                    if (!(await syncControlFromBackend(`暂停检查: 已读取职位详情 ${jobInfo.title}`))) {
                        finishJobProgress('暂停停止');
                        return;
                    }
                    if (!(await ensureSessionLimitAvailable())) {
                        finishJobProgress('本次上限停止');
                        return;
                    }
                    if (jobInfo.talked) {
                        const reason = jobInfo.talked_reason || '页面显示已沟通';
                        logger.add(`职位 [${jobInfo.title}] ${reason}，下一个`);
                        await api.createAction('already_contacted', { reason }, jobInfo, 'completed');
                        await api.event('decision_skip', `跳过已沟通职位: ${jobInfo.title}`, 'script', 'info', { title: jobInfo.title, url: href, reason });
                        finishJobProgress('已沟通跳过');
                        setTimeout(loop, 0);
                        return;
                    }

                    if (!(await ensureSessionLimitAvailable())) {
                        finishJobProgress('本次上限停止');
                        return;
                    }
                    logger.add(`开始计算职位 [${jobInfo.title}] 的匹配度`);
                    setSearchAction(`分析职位: ${jobInfo.title}`);
                    await api.event('job_analysis_started', `开始分析职位: ${jobInfo.title}`, 'script', 'info', { title: jobInfo.title, salary: jobInfo.salary });
                    const analysis = await api.analyzeJob({
                        title: jobInfo.title,
                        salary: jobInfo.salary,
                        detail: jobInfo.detail,
                        company: jobInfo.company || '',
                        city: jobInfo.city || '',
                        url: href,
                        talked: Boolean(jobInfo.talked),
                        talked_reason: jobInfo.talked_reason || '',
                    });
                    const score = analysis.total_score;
                    logger.add(`匹配度: ${score}`);
                    if (analysis.match_reason) logger.add(`判断原因: ${analysis.match_reason}`);
                    if (analysis.recommendation) logger.add(`推荐动作: ${analysis.recommendation}`);
                    await api.event('job_analysis_finished', `职位分析完成: ${jobInfo.title} / ${score}`, 'script', 'info', { title: jobInfo.title, score, recommendation: analysis.recommendation, risks: analysis.risks || [] });
                    if (analysis.risks && analysis.risks.length) {
                        logger.add(`风险点: ${analysis.risks.join('；')}`);
                    }
                    if (!(await syncControlFromBackend(`暂停检查: 职位分析完成 ${jobInfo.title}`))) {
                        finishJobProgress('暂停停止');
                        return;
                    }
                    if (analysis.recommendation === 'greet' && score >= OPTIONS.thread) {
                        jobInfo.score = score;
                        if (!(await ensureSessionLimitAvailable())) {
                            finishJobProgress('本次上限停止');
                            return;
                        }
                        setSearchAction(`准备打招呼: ${jobInfo.title}`);
                        if (!(await syncControlFromBackend(`暂停检查: 准备打招呼 ${jobInfo.title}`))) {
                            finishJobProgress('暂停停止');
                            return;
                        }
                        if (!(await ensureSessionLimitAvailable())) {
                            finishJobProgress('本次上限停止');
                            return;
                        }
                        await sendGreetingFromSearch(jobInfo, href);
                    } else {
                        if (analysis.recommendation === 'wait_for_confirm') {
                            await recordGreetingSuggestion(jobInfo, analysis, href, analysis.match_reason || '模型建议人工确认，不自动打招呼');
                        } else {
                            await api.event('decision_skip', `跳过职位: ${jobInfo.title} / ${score}`, 'script', 'info', { title: jobInfo.title, score, recommendation: analysis.recommendation, reason: analysis.match_reason || analysis.blocked_reason || '' });
                        }
                        finishJobProgress('跳过');
                        setTimeout(loop, 0);
                    }
                } catch (e) {
                    if (tools.isPlatformLimitError(e)) {
                        await handlePageFailure(tools.platformLimitReason(e), 'platform_limit', 'search');
                        return;
                    }
                    if (tools.isElementMissingError(e)) {
                        await handlePageFailure(String(e), 'element_retry', 'search');
                        return;
                    }
                    if (tools.isManualInterruptionError(e)) {
                        await handleManualInterruption(tools.manualInterruptionReason(e), 'search');
                        return;
                    }
                    console.log(e);
                    logger.add(`循环时出错: ${e}`);
                    setSearchAction(`循环出错，稍后继续: ${e}`);
                    await api.event('loop_failed', `循环时出错: ${e}`, 'script', 'error');
                    const errorText = String(e);
                    finishJobProgress(errorText.includes('详情') || errorText.includes('get-job-info') ? '详情失败跳过' : '异常跳过');
                    setTimeout(loop, 1000);
                } finally {
                    loopRunning = false;
                }
            };

            // 主函数
            const main = async () => {
                try {
                    if (booting || started) return;
                    if (!(await ensureSearchLease('启动自动化'))) return;
                    booting = true;
                    started = true;
                    resetProgress();
                    if (!tools.getGreetSession().runId || tools.getGreetSession().ended) {
                        beginGreetSession('开始新一轮');
                    }
                    setSearchAction('程序启动，读取配置');
                    logger.add('--程序启动--');
                    const bootStatus = await api.heartbeat('search', 'running', '程序启动', scriptHeartbeatDetail());
                    applyBackendConfig(bootStatus.config);
                    lastBackendRunId = bootStatus.run_id || lastBackendRunId;
                    await ensureSessionForBackendRun(lastBackendRunId, 'program_start');
                    // 开始广播
                    startBroadcast();
                    // 获取标签
                    setSearchAction('读取简历画像标签');
                    this.tags = await api.getTags();
                    if (!this.tags.length) {
                        logger.add('请先在 CLI 中生成简历画像');
                        await api.heartbeat('search', 'error', '缺少简历画像');
                        return;
                    }
                    logger.add('获取标签成功: ' + this.tags.join('、'));
                    const recentJobs = await api.getRecentJobs();
                    backendProcessedHrefs.clear();
                    for (const item of recentJobs) {
                        const href = tools.normalUrl(item.url || '');
                        if (href) backendProcessedHrefs.add(href);
                    }
                    if (backendProcessedHrefs.size) {
                        await api.event('recent_jobs_loaded', `已加载近期处理职位 ${backendProcessedHrefs.size} 个`, 'script', 'info', {
                            count: backendProcessedHrefs.size,
                            hours: OPTIONS.recentProcessedHours,
                        });
                    }
                    // 获取自我介绍
                    setSearchAction('读取已确认打招呼用语');
                    this.introduce = await api.getIntroduce();
                    if (!this.introduce) {
                        logger.add('请先在 CLI 中生成并启用打招呼用语');
                        await api.heartbeat('search', 'error', '缺少已启用打招呼用语');
                        return;
                    }
                    logger.add('获取自我介绍成功: ' + this.introduce);
                    // 开始搜索
                    if (currentTagIdx >= this.tags.length) {
                        currentTagIdx = 0;
                    }
                    setSearchAction(`准备搜索关键词: ${this.tags[currentTagIdx]}`);
                    await search(this.tags[currentTagIdx]);
                    await tools.actionSleep(1500);
                    const hasJobs = await nextPage();
                    if (!hasJobs) {
                        const hasNextKeyword = await switchToNextKeyword('搜索后没有读取到职位列表');
                        if (hasNextKeyword) {
                            loop();
                        } else {
                            logger.add('所有关键词暂无新职位，稍后重新轮询');
                            await api.heartbeat('search', 'running', '所有关键词暂无新职位，稍后重新轮询');
                            setTimeout(loop, OPTIONS.actionDelayMs);
                        }
                        return;
                    }
                    // 开始循环
                    loop();
                } catch (e) {
                    if (tools.isPlatformLimitError(e)) {
                        await handlePageFailure(tools.platformLimitReason(e), 'platform_limit', 'search');
                        return;
                    }
                    if (tools.isElementMissingError(e)) {
                        await handlePageFailure(String(e), 'element_retry', 'search');
                        return;
                    }
                    if (tools.isManualInterruptionError(e)) {
                        await handleManualInterruption(tools.manualInterruptionReason(e), 'search');
                        return;
                    }
                    started = false;
                    this.pause = true;
                    logger.add(`启动失败: ${e}`);
                    await api.heartbeat('search', 'error', `启动失败: ${e}`);
                } finally {
                    booting = false;
                }
            };

            // 初始化
            const init = async () => {
                const res = await api.heartbeat('search', 'idle', '等待 CLI start', scriptHeartbeatDetail());
                applyBackendConfig(res.config);
                lastBackendRunId = res.run_id || lastBackendRunId;
                lastBackendControl = res.control || lastBackendControl;
                if (res.offline) {
                    noteBackendOffline('后端未连接：请先运行 python main.py，并确认油猴脚本允许连接 127.0.0.1');
                    return;
                }
                noteBackendOnline();
                await api.event('script_ready', `脚本就绪: ${OPTIONS.scriptVersion}`, 'script', 'info', {
                    version: OPTIONS.scriptVersion,
                    serverHost: OPTIONS.serverHost,
                    threshold: OPTIONS.thread,
                    sessionGreetLimit: OPTIONS.sessionGreetLimit,
                    sessionGreetCount: tools.getSessionGreetCount(),
                });
                logger.add('等待 CLI 输入 start 开始自动化');
                if (res.should_start || res.control === 'running') {
                    if (!(await ensureSearchLease('初始化自动继续'))) return;
                    await ensureSessionForBackendRun(lastBackendRunId, 'init_running');
                    if (!tools.getGreetSession().runId || tools.getGreetSession().ended) {
                        beginGreetSession('开始新一轮');
                    }
                    logger.setPaused(false);
                    this.pause = false;
                    main();
                    return;
                }
                // 从其他页面跳回搜索页时，仍然尊重 CLI 控制状态。
                if (searchPageOpenedAt - tools.getTimestamp(this.targets.search) < OPTIONS.timestampTimeout && res.control !== 'paused') {
                    if (!(await ensureSearchLease('搜索页恢复'))) return;
                    await ensureSessionForBackendRun(lastBackendRunId, 'search_page_restore');
                    this.pause = false;
                    main();
                }
            };

            init();
        }

        // 详情页
        __detail() {
            const api = new Api();
            // 注册广播
            const startBroadcast = () => {
                this.__broadcast(this.targets.detail);
            };
            startBroadcast();

            // 鑾峰彇鑱屼綅淇℃伅
            const getJobInfo = async () => {
                const platformLimit = tools.detectPlatformLimit();
                if (platformLimit) throw new Error(`平台次数限制: ${platformLimit}`);
                const interruption = tools.detectManualInterruption();
                if (interruption) throw new Error(`需要人工处理: ${interruption}`);
                await tools.waitForOne(SELECTORS.ZHIPIN.DETAIL.JOBNAME_CANDIDATES, 20000);
                await tools.waitForOne(SELECTORS.ZHIPIN.DETAIL.DETAIL_CANDIDATES, 20000);
                const chatBtn = tools.findOne(SELECTORS.ZHIPIN.DETAIL.STARTCHAT);
                const title = tools.textOf(SELECTORS.ZHIPIN.DETAIL.JOBNAME_CANDIDATES);
                const salary = tools.textOf(SELECTORS.ZHIPIN.DETAIL.SALARY_CANDIDATES);
                const detail = tools.textOf(SELECTORS.ZHIPIN.DETAIL.DETAIL_CANDIDATES);
                const company = tools.textOf(SELECTORS.ZHIPIN.DETAIL.COMPANY_CANDIDATES);
                const city = tools.textOf(SELECTORS.ZHIPIN.DETAIL.CITY_CANDIDATES);
                if (!title) throw new Error('未找到职位名称');
                if (!salary) throw new Error('未找到职位薪资');
                if (!detail) throw new Error('未找到职位描述');
                const chatUrl = chatBtn && (chatBtn.getAttribute(SELECTORS.ZHIPIN.DETAIL.CHATURL) || chatBtn.getAttribute('href') || chatBtn.dataset.redirectUrl);
                const addUrl = chatBtn && (chatBtn.dataset.url || chatBtn.getAttribute('data-url') || chatBtn.getAttribute('href'));
                const talkedReason = tools.contactedReasonFromElement(chatBtn);
                if (!chatBtn || (!tools.normalUrl(chatUrl) && !tools.normalUrl(addUrl) && !chatBtn.dataset.isfriend)) {
                    throw new Error('未找到打招呼入口，可能页面结构已变化或需要人工处理');
                }
                return {
                    title,
                    salary,
                    detail,
                    company,
                    city,
                    chatUrl: tools.normalUrl(chatUrl),
                    addUrl: tools.normalUrl(addUrl),
                    talked: Boolean(talkedReason),
                    talked_reason: talkedReason,
                    source: 'detail',
                };
            };
            // 来自搜索页
            const fromSearchPage = async () => {
                const jobInfo = await getJobInfo();
                // 把职位信息发送给搜索页
                await api.event('job_detail_received', `详情页读取职位: ${jobInfo.title}`, 'script', 'info', jobInfo);
                await this.broadcast.send(this.targets.search, this.bcTypes.GET_JOB_INFO, jobInfo);
                setTimeout(() => window.close(), 500);
            };

            // 来自聊天页
            const fromChatPage = async () => {
                const jobInfo = await getJobInfo();
                // 把职位信息发送给聊天页
                await api.event('job_detail_received', `聊天页读取职位: ${jobInfo.title}`, 'script', 'info', jobInfo);
                await this.broadcast.send(
                    this.targets.chat,
                    this.bcTypes.GET_JOB_INFO,
                    jobInfo
                );
                window.close();
            };

            // 主函数
            const main = async () => {
                try {
                    // 判断来源
                    const now = new Date().getTime();
                    const detailOpenedAt = tools.getTimestamp(this.targets.detail);
                    const chatOpenedAt = tools.getTimestamp(this.targets.chat);
                    const detailAge = detailOpenedAt ? now - detailOpenedAt : null;
                    const chatAge = chatOpenedAt ? now - chatOpenedAt : null;
                    const isNamedDetailWindow = window.name === this.targets.detail;
                    const isRecentDetailWindow = detailAge !== null && detailAge < OPTIONS.timestampTimeout;
                    const isRecentChatWindow = chatAge !== null && chatAge < OPTIONS.timestampTimeout;
                    const isFromSearch = isNamedDetailWindow || isRecentDetailWindow;
                    const isFromChat = !isFromSearch && isRecentChatWindow;
                    await api.heartbeat('detail', 'running', `详情页已启动: ${location.pathname}`, {
                        path: location.pathname,
                        windowName: window.name,
                        isFromSearch,
                        isFromChat,
                        detailAge,
                        chatAge,
                    });

                    if (isFromSearch) {
                        await fromSearchPage();
                    } else if (isFromChat) {
                        await fromChatPage();
                    } else {
                        await api.heartbeat('detail', 'idle', '详情页独立打开，未执行自动动作');
                    }
                } catch (e) {
                    const now = new Date().getTime();
                    const detailOpenedAt = tools.getTimestamp(this.targets.detail);
                    const detailAge = detailOpenedAt ? now - detailOpenedAt : null;
                    const isFromSearch = window.name === this.targets.detail || (detailAge !== null && detailAge < OPTIONS.timestampTimeout);
                    const manualReason = tools.manualInterruptionReason(e);
                    if (manualReason && isFromSearch) {
                        await this.broadcast.send(this.targets.search, this.bcTypes.GET_JOB_INFO, {
                            manual_intervention: true,
                            reason: manualReason,
                            error: String(e),
                            source: 'detail_error',
                        }).catch(async (sendError) => {
                            await api.event('broadcast_send_failed', `详情页人工处理回传失败: ${sendError}`, 'script', 'error', {
                                path: location.pathname,
                                windowName: window.name,
                            });
                        });
                        setTimeout(() => window.close(), 500);
                    }
                    const platformReason = tools.platformLimitReason(e);
                    const elementMissing = tools.isElementMissingError(e);
                    if ((platformReason || elementMissing) && isFromSearch) {
                        await this.broadcast.send(this.targets.search, this.bcTypes.GET_JOB_INFO, {
                            page_failure: true,
                            failure_kind: platformReason ? 'platform_limit' : 'element_retry',
                            reason: platformReason || String(e),
                            error: String(e),
                            source: 'detail_error',
                        }).catch(async (sendError) => {
                            await api.event('broadcast_send_failed', `详情页页面失败回传失败: ${sendError}`, 'script', 'error', {
                                path: location.pathname,
                                windowName: window.name,
                            });
                        });
                        setTimeout(() => window.close(), 500);
                    }
                    await api.heartbeat('detail', 'error', String(e), { path: location.pathname, windowName: window.name });
                    await api.event('job_detail_failed', `详情页读取失败: ${e}`, 'script', 'error', { path: location.pathname, windowName: window.name });
                }
            };
            main();
        }

        // 聊天页
        async __chat() {
            const pageApi = new Api();
            // 注册广播
            const startBroadcast = (target = this.targets.chat) => {
                this.__broadcast(target);
            };

            // 发送消息
            const getSelfMessageSnapshot = () => {
                const nodes = Array.from(document.querySelectorAll('.item-myself'));
                const texts = nodes.map((node) => {
                    const msgBox = node.querySelector(SELECTORS.ZHIPIN.CHAT.MSGCONTENT);
                    return String((msgBox || node).innerText || (msgBox || node).textContent || '').trim();
                }).filter(Boolean);
                return {
                    count: nodes.length,
                    lastText: texts[texts.length - 1] || '',
                };
            };

            const waitForMessageSendConfirmed = async (text, inputEl, beforeSnapshot, timeout = 7000) => {
                const expectedPrefix = String(text || '').trim().slice(0, 12);
                const startedAt = Date.now();
                while (Date.now() - startedAt < timeout) {
                    const afterSnapshot = getSelfMessageSnapshot();
                    const inputText = String(
                        ('value' in inputEl ? inputEl.value : (inputEl.innerText || inputEl.textContent)) || ''
                    ).trim();
                    const messageAdded = afterSnapshot.count > beforeSnapshot.count;
                    const messageMatches = expectedPrefix && afterSnapshot.lastText.includes(expectedPrefix);
                    const inputCleared = !inputText || !inputText.includes(expectedPrefix);
                    if (messageMatches || (messageAdded && inputCleared)) {
                        return {
                            confirmed: true,
                            beforeCount: beforeSnapshot.count,
                            afterCount: afterSnapshot.count,
                            lastText: afterSnapshot.lastText.slice(0, 80),
                            inputCleared,
                        };
                    }
                    await tools.asyncSleep(300);
                }
                const afterSnapshot = getSelfMessageSnapshot();
                return {
                    confirmed: false,
                    beforeCount: beforeSnapshot.count,
                    afterCount: afterSnapshot.count,
                    lastText: afterSnapshot.lastText.slice(0, 80),
                };
            };

            const sendMsg = (text) => {
                return new Promise(async (resolve, reject) => {
                    try {
                        const platformLimit = tools.detectPlatformLimit();
                        if (platformLimit) throw new Error(`平台次数限制: ${platformLimit}`);
                        const interruption = tools.detectManualInterruption();
                        if (interruption) throw new Error(`需要人工处理: ${interruption}`);
                        if (!String(text || '').trim()) throw new Error('发送内容为空');
                        await pageApi.event('message_send_started', `准备发送消息: ${String(text).slice(0, 40)}`, 'script', 'info', { preview: String(text).slice(0, 120) });
                        const ipt = await tools.endlessFind(SELECTORS.ZHIPIN.CHAT.CHATINPUT);
                        const actualText = tools.inputEditableText(ipt, text);
                        if (!actualText || !actualText.includes(String(text).slice(0, 10))) {
                            const error = new Error('输入框写入后内容校验失败');
                            error.detail = {
                                input: tools.elementBrief(ipt),
                                expectedLength: String(text).length,
                                actualLength: String(actualText || '').length,
                            };
                            throw error;
                        }
                        await tools.actionSleep(600);
                        const btn = await tools.endlessFind(SELECTORS.ZHIPIN.CHAT.MSGSEND);
                        if (!tools.isVisible(btn) || tools.isDisabled(btn)) {
                            const error = new Error('发送按钮不可用，可能需要人工确认页面状态');
                            error.detail = {
                                button: tools.elementBrief(btn),
                                visible: tools.isVisible(btn),
                                disabled: tools.isDisabled(btn),
                                input: tools.elementBrief(ipt),
                            };
                            throw error;
                        }
                        const beforeSnapshot = getSelfMessageSnapshot();
                        btn.click();
                        const confirmation = await waitForMessageSendConfirmed(text, ipt, beforeSnapshot);
                        if (!confirmation.confirmed) {
                            const error = new Error('message_send_unconfirmed');
                            error.detail = {
                                button: tools.elementBrief(btn),
                                input: tools.elementBrief(ipt),
                                ...confirmation,
                            };
                            throw error;
                        }
                        await pageApi.event('message_send_finished', '消息已点击发送', 'script', 'info', {
                            button: tools.elementBrief(btn),
                            input: tools.elementBrief(ipt),
                            length: String(text).length,
                            confirmation,
                        });
                        resolve();
                    } catch (e) {
                        await pageApi.event('message_send_failed', `消息发送失败: ${e}`, 'script', 'error', e.detail || {});
                        reject(e);
                    }
                })
            };

            // 打招呼
            const closeTemporaryChatPage = async (requestId) => {
                tools.releaseGreetClaim(requestId);
                setTimeout(() => {
                    window.close();
                    setTimeout(() => {
                        pageApi.event('temporary_chat_close_failed', '临时打招呼页未能自动关闭，可手动关闭', 'script', 'warning', {
                            requestId,
                            url: location.href,
                        }).catch(() => null);
                        banner('临时打招呼页已完成，可关闭');
                    }, 1500);
                }, 800);
            };

            const sayHi = async (claim = {}) => {
                const claimedContext = claim.context || tools.getGreetContext();
                const greetRequestId = claimedContext.requestId || '';
                const greetAttempt = Number(claimedContext.attempt || 1);
                const ensureCurrentGreetRequest = () => {
                    if (!greetRequestId) return;
                    const current = tools.getGreetContext();
                    if (current.requestId !== greetRequestId) {
                        throw new Error('greet_request_stale');
                    }
                };
                startBroadcast(this.targets.chatGreet);

                // 心跳
                let count = 0;
                let heartbeatActive = true;
                const loop = () => {
                    if (!heartbeatActive || !this.broadcast) return;
                    this.broadcast.sendAndReceive(
                        this.targets.search,
                        this.bcTypes.HEART_BEAT,
                        { count: ++count }
                    ).then((res) => {
                        if (res.success) {
                            setTimeout(loop, 1000);
                        } else {
                            throw new Error('心跳失联');
                        }
                    }).catch(async (e) => {
                        heartbeatActive = false;
                        await pageApi.heartbeat('chat_greet', 'error', `打招呼页心跳失联: ${e}`);
                        await pageApi.event('greet_heartbeat_failed', `打招呼页心跳失联: ${e}`, 'script', 'error');
                    });
                };
                loop();

                try {
                    await pageApi.heartbeat('chat_greet', 'running', '准备打招呼');
                    await pageApi.event('greet_started', '打招呼窗口准备发送', 'script');
                    const introduce = (await this.broadcast.sendAndReceive(this.targets.search, this.bcTypes.SAY_HI, {
                        greetRequestId,
                        attempt: greetAttempt,
                    })).introduce;
                    if (!introduce) throw new Error('未启用打招呼用语');
                    await tools.actionSleep();
                    ensureCurrentGreetRequest();
                    await sendMsg(introduce);
                    const greetContext = claimedContext || {};
                    await pageApi.createAction('greet', {
                        message: introduce,
                        context: greetContext,
                    }, greetContext, 'completed');
                    const sessionGreetCount = tools.increaseSessionGreetCount();
                    await pageApi.heartbeat('chat_greet', 'running', '打招呼成功');
                    await pageApi.event(
                        'greet_finished',
                        `打招呼消息已发送，本轮计数 ${sessionGreetCount}`,
                        'script',
                        'info',
                        { sessionGreetCount, runId: tools.getGreetSession().runId, requestId: greetRequestId, attempt: greetAttempt }
                    );
                    heartbeatActive = false;
                    this.broadcast.send(this.targets.search, this.bcTypes.SAY_HI, {
                        success: true,
                        sessionGreetCount,
                        greetRequestId,
                        attempt: greetAttempt,
                    }).catch(async (sendError) => {
                        await pageApi.event('broadcast_send_failed', `打招呼结果回传失败: ${sendError}`, 'script', 'error');
                    }).finally(() => {
                        this.broadcast.destroy();
                        closeTemporaryChatPage(greetRequestId);
                    });
                } catch (e) {
                    heartbeatActive = false;
                    await pageApi.heartbeat('chat_greet', 'error', String(e));
                    await pageApi.event('greet_failed', `打招呼失败: ${e}`, 'script', 'error');
                    this.broadcast.send(this.targets.search, this.bcTypes.SAY_HI, {
                        success: false,
                        error: String(e),
                        greetRequestId,
                        attempt: greetAttempt,
                        retryable: !(tools.isPlatformLimitError(e) || tools.isManualInterruptionError(e)),
                    }).catch(async (sendError) => {
                        await pageApi.event('broadcast_send_failed', `打招呼失败结果回传失败: ${sendError}`, 'script', 'error');
                    }).finally(() => {
                        this.broadcast.destroy();
                        closeTemporaryChatPage(greetRequestId);
                    });
                }
            };


            // 主函数
            const main = async () => {
                // 判断来源
                const now = new Date().getTime();
                const greetOpenedAt = tools.getTimestamp(this.targets.chatGreet);
                const greetAge = greetOpenedAt ? now - greetOpenedAt : null;
                let greetContext = tools.getGreetContext();
                const greetClaim = tools.claimGreetContext();
                if (greetClaim.context && greetClaim.context.requestId) {
                    greetContext = greetClaim.context;
                }
                const contextChatUrl = tools.normalUrl(greetContext.chatUrl || '');
                const currentChatUrl = tools.normalUrl(location.href) || location.href;
                const isLikelySameChat = contextChatUrl
                    ? currentChatUrl.split('#')[0] === contextChatUrl.split('#')[0]
                    : Boolean(greetContext.url || greetContext.title || greetContext.greeting);
                const isRecentGreetWindow = greetAge !== null && greetAge < OPTIONS.timestampTimeout;
                const hasGreetContext = Boolean(greetContext && (
                    greetContext.requestId
                    || greetContext.chatUrl
                    || greetContext.url
                    || greetContext.title
                    || greetContext.greeting
                ));
                const fallbackClaim = (!greetClaim.claimed && isRecentGreetWindow && hasGreetContext)
                    ? tools.claimTimestampGreetFallback(greetOpenedAt)
                    : { claimed: false, reason: '' };
                const canUseTimestampFallback = isRecentGreetWindow
                    && hasGreetContext
                    && !greetClaim.claimed
                    && fallbackClaim.claimed
                    && !['claimed_by_other_page'].includes(String(greetClaim.reason || ''));
                const isGreet = Boolean(greetClaim.claimed) || canUseTimestampFallback;

                if (isGreet) {
                    const effectiveClaim = greetClaim.claimed
                        ? greetClaim
                        : {
                            claimed: true,
                            reason: 'timestamp_fallback',
                            context: {
                                ...greetContext,
                                createdAt: Date.now(),
                                attempt: Number(greetContext.attempt || 1),
                                maxAttempts: Number(greetContext.maxAttempts || OPTIONS.greetMaxAttempts || 3),
                            },
                        };
                    if (canUseTimestampFallback) {
                        await pageApi.event('greet_chat_timestamp_fallback', '打招呼页未认领到 requestId，已按 chatGreet 时间戳继续', 'script', 'warning', {
                            claimReason: greetClaim.reason || '',
                            greetAge,
                            contextChatUrl,
                            currentChatUrl,
                            hasContext: hasGreetContext,
                            fallbackClaimReason: fallbackClaim.reason || '',
                        });
                    }
                    if (!isLikelySameChat) {
                        await pageApi.event('greet_chat_url_mismatch', '打招呼聊天页 URL 与打开时 URL 不一致，已按 requestId 继续', 'script', 'warning', {
                            requestId: greetContext.requestId || '',
                            contextChatUrl,
                            currentChatUrl,
                        });
                    }
                    sayHi(effectiveClaim);
                }
                else {
                    // 日志
                    await pageApi.heartbeat('chat', 'idle', '普通聊天页已忽略：本工具只执行打招呼');
                    await pageApi.event('chat_ignored_not_greet_page', '普通聊天页已忽略：本工具只执行打招呼，不处理附件或简历卡片', 'script', 'info', {
                        path: location.pathname,
                        url: location.href,
                        greetAge,
                        claimReason: greetClaim.reason || '',
                        hasGreetContext,
                    });
                }
            };
            main();
        }

        // 运行
        run(tagIdx = 0) {
            const path = location.pathname;
            // 在搜索页
            if (tools.isSearchPath(path)) {
                this.__search(tagIdx);
            }
            // 在详情页
            else if (tools.pathMatches(this.whiteList.detail)) {
                this.__detail();
            }
            // 在聊天页
            else if (tools.pathMatches(this.whiteList.chat)) {
                this.__chat();
            }
            // 城市首页，例如 /xian/，自动进入职位搜索页。
            else if (tools.isCityHomePath(path) || path === '/') {
                const api = new Api();
                const interruption = tools.detectManualInterruption();
                if (interruption) {
                    api.heartbeat('unmatched', 'error', `需要人工处理: ${interruption}`, { path });
                    api.event('manual_intervention_required', `页面需要人工处理: ${interruption}`, 'script', 'error', { path });
                    new Logger();
                    return;
                }
                api.event('script_city_home_redirect', `城市首页自动进入职位搜索页: ${path}`, 'script', 'info', {
                    path,
                    target: SEARCHPATH.zhipin,
                });
                const logger = new Logger(() => {
                    tools.openTabNSetTimestamp(SEARCHPATH.zhipin, this.targets.search, true);
                });
                logger.add(`当前是城市首页 ${path}，即将进入职位搜索页`);
                setTimeout(() => {
                    tools.openTabNSetTimestamp(SEARCHPATH.zhipin, this.targets.search, true);
                }, 800);
            }
            // 其他未知页面只提示，不盲目操作。
            else {
                new Api().event('script_page_unmatched', `未匹配页面路径: ${path}`, 'script', 'info', { path });
                new Logger(() => {
                    tools.openTabNSetTimestamp(SEARCHPATH.zhipin, this.targets.search, true);
                });
            }
        }
    }

    const chatbotZhou = new Zhipin().run();
})();
