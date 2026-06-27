// ==UserScript==
// @name         Job Seeker
// @namespace    http://tampermonkey.net/
// @version      2026.06.26.3
// @description  Job Seeker 篡改猴插件
// @author       Chatbot-Zhou
// @match        https://www.zhipin.com/*
// @icon         https://www.google.com/s2/favicons?sz=64&domain=zhipin.com
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @updateURL    http://127.0.0.1:33333/web_script.user.js
// @downloadURL  http://127.0.0.1:33333/web_script.user.js
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    // OriginalAuthor: 嘎嘣脆的贝爷

    // 配置项
    const OPTIONS = {
        scriptVersion: '2026.06-cli-autogreet.19',
        resumeIndex: 0, // 第几份简历，从 0 开始递增
        serverHost: 'http://127.0.0.1:33333', // 本地服务的主机地址
        thread: 60, // 分数阈值，低于这个就不发消息了
        timestampTimeout: 120000, // 页面跳转来源标记有效期，单位毫秒。
        jobInfoResponseTimeout: 90000, // 详情页回传职位信息的最长等待时间。
        onlyGreet: true, // 仅辅助打招呼，不自动扫描聊天页。
        sessionGreetLimit: 50, // 本次打招呼上限，后端配置会覆盖这里。
        actionDelayMs: 2500, // 页面动作之间的保守等待时间。
        manualInterventionMaxRetries: 3, // 人工校验自动恢复次数，连续失败后暂停。
    };

    let backendOfflineNotified = false;
    let backendOfflineFailures = 0;
    const BACKEND_OFFLINE_NOTIFY_THRESHOLD = 2;

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

    // 工具
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
                    reject(new Error('未找到目标元素'));
                }, timeout);

                // 定义MutationObserver回调
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

                // 开始观察整个文档的DOM变化
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
        getTimestamp(key) {
            return Number(localStorage.getItem(key));
        },
        openTabNSetTimestamp(href, key, self = false) {
            localStorage.setItem(key, new Date().getTime());
            return window.open(href, self ? '_self' : key);
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
        sessionStateKey: '__chatbot_zhou_greet_session',
        getGreetSession() {
            try {
                const value = JSON.parse(localStorage.getItem(this.sessionStateKey) || '{}');
                return {
                    runId: String(value.runId || ''),
                    count: Number(value.count || 0),
                    startedAt: String(value.startedAt || ''),
                    ended: Boolean(value.ended),
                };
            } catch (e) {
                return { runId: '', count: 0, startedAt: '', ended: true };
            }
        },
        saveGreetSession(session) {
            const state = {
                runId: String(session.runId || ''),
                count: Math.max(0, Number(session.count || 0)),
                startedAt: String(session.startedAt || new Date().toISOString()),
                ended: Boolean(session.ended),
            };
            localStorage.setItem(this.sessionStateKey, JSON.stringify(state));
            return state;
        },
        startGreetSession(force = false) {
            const current = this.getGreetSession();
            if (!force && current.runId && !current.ended) {
                return current;
            }
            return this.saveGreetSession({
                runId: `run_${Date.now()}_${Math.floor(Math.random() * 100000)}`,
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
            ];
            return patterns.find(pattern => content.includes(pattern)) || '';
        },
        detectManualInterruption() {
            const text = document.body ? document.body.innerText : '';
            return this.detectInterruptionText(text);
        },
        manualInterruptionReason(value) {
            const content = String(value || '');
            const detected = this.detectInterruptionText(content);
            if (detected) return detected;
            const explicit = content.match(/需要人工处理[:：]\s*([^;；\n\r]+)/);
            if (explicit && explicit[1]) return explicit[1].trim();
            const detail = content.match(/详情页需要人工处理[:：]\s*([^;；\n\r]+)/);
            if (detail && detail[1]) return detail[1].trim();
            return '';
        },
        isManualInterruptionError(value) {
            return Boolean(this.manualInterruptionReason(value));
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
                        // storage 方案需要先写入再删除，触发事件
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
            if (typeof fn !== 'function') throw new Error('回调必须是函数');
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

    // api请求
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
            // 校验函数
            if (startFn && !Function.prototype.isPrototypeOf(startFn)) {
                throw new Error('参数错误，startFn应为函数');
            }
            if (pauseFn && !Function.prototype.isPrototypeOf(pauseFn)) {
                throw new Error('参数错误，pauseFn应为函数');
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

    // boss 直聘
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
            let lastJobListEventKey = '';
            // 缓存
            let started = false;
            let booting = false;
            let loopRunning = false;
            let waitingForGreeting = false;
            let greetTimeoutId = null;
            let currentSearchAction = '等待启动';
            let lastBackendControl = 'paused';
            const manualRecoveryStateKey = '__job_seeker_manual_recovery';
            let manualInterventionRetryCount = 0;

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

            const loadedManualRecovery = loadManualRecoveryState();
            if (Number.isFinite(Number(loadedManualRecovery.nextTagIdx))) {
                currentTagIdx = Math.max(0, Number(loadedManualRecovery.nextTagIdx));
            }
            if (Number.isFinite(Number(loadedManualRecovery.retryCount))) {
                manualInterventionRetryCount = Math.max(0, Number(loadedManualRecovery.retryCount));
            }

            const scriptHeartbeatDetail = () => ({
                version: OPTIONS.scriptVersion,
                threshold: OPTIONS.thread,
                sessionGreetLimit: OPTIONS.sessionGreetLimit,
                sessionGreetCount: tools.getSessionGreetCount(),
                runId: tools.getGreetSession().runId,
            });

            const setSearchAction = (action) => {
                currentSearchAction = action || (started ? '搜索/浏览职位' : '等待启动');
            };

            const getSearchAction = () => {
                if (this.pause) return '暂停中';
                return currentSearchAction || (started ? '搜索/浏览职位' : '等待启动');
            };

            // 日志启动暂停事件
            const logger = new Logger(async () => {
                const res = await api.heartbeat('search', this.pause ? 'paused' : 'idle', '等待 CLI start', scriptHeartbeatDetail());
                applyBackendConfig(res.config);
                if (res.control === 'running' || res.should_start) {
                    this.pause = false;
                    logger.setPaused(false);
                    started ? loop() : main();
                    return;
                }
                logger.setPaused(true);
                this.pause = true;
                logger.add('请回到 CLI 输入 start，确认本轮岗位标签和本次打招呼上限后开始');
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
                const session = tools.startGreetSession(true);
                resetProgress();
                if (reason) {
                    logger.add(`本轮打招呼计数已重置: ${reason}`);
                }
                return session;
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
                    logger.setPaused(true);
                    this.pause = true;
                    return false;
                }
                if (res.should_pause || res.control === 'paused') {
                    if (!this.pause) logger.add('CLI 已暂停自动化');
                    logger.setPaused(true);
                    this.pause = true;
                    return false;
                }
                if (res.should_start || res.control === 'running') {
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
                    if (!started && !booting) {
                        main();
                    } else if (started && !booting && !waitingForGreeting) {
                        loop();
                    }
                }
            }, 3000);

            const startGreetingWait = (jobInfo) => {
                waitingForGreeting = true;
                if (greetTimeoutId) clearTimeout(greetTimeoutId);
                greetTimeoutId = setTimeout(async () => {
                    if (!waitingForGreeting) return;
                    waitingForGreeting = false;
                    logger.add(`职位 [${jobInfo.title}] 打招呼窗口超时，下一个`);
                    await api.event('greet_failed', `打招呼窗口超时: ${jobInfo.title}`, 'script', 'error', { title: jobInfo.title });
                    finishJobProgress('打招呼超时');
                    loop();
                }, 60000);
            };

            const finishGreetingWait = () => {
                waitingForGreeting = false;
                if (greetTimeoutId) {
                    clearTimeout(greetTimeoutId);
                    greetTimeoutId = null;
                }
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
                chatListener();
                // 心跳监听
                heartBeatListener();
            };

            // 执行搜索
            const search = async (kw) => {
                try {
                    setSearchAction(`搜索关键词: ${kw}`);
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
                    logger.add('搜索出错');
                    await api.event('search_failed', `搜索出错: ${e}`, 'script', 'error', { keyword: kw });
                    throw new Error('搜索出错');
                }
            };

            // 获取职位链接
            const getJobHrefs = async () => {
                try {
                    setSearchAction('读取职位列表');
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
                    let newHrefs = hrefs.filter(href => !seenJobHrefs.has(href));
                    const startedAt = Date.now();
                    while (!newHrefs.length && hrefs.length <= elsLen && Date.now() - startedAt < 5000) {
                        await tools.asyncSleep(500);
                        hrefs = collect();
                        newHrefs = hrefs.filter(href => !seenJobHrefs.has(href));
                    }
                    const eventKey = `${hrefs.length}:${newHrefs.length}:${hrefs[hrefs.length - 1] || ''}`;
                    if (eventKey !== lastJobListEventKey) {
                        lastJobListEventKey = eventKey;
                        await api.event('job_list_found', `发现职位链接 ${hrefs.length} 个，新职位 ${newHrefs.length} 个`, 'script', 'info', { count: hrefs.length, newCount: newHrefs.length });
                    }
                    return [newHrefs, hrefs];
                } catch (e) {
                    if (tools.isManualInterruptionError(e)) throw e;
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

            document.nextPage = nextPage

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

            // 获取职位信息
            const getJobInfo = async (href) => {
                const interruption = tools.detectManualInterruption();
                if (interruption) {
                    throw new Error(`需要人工处理: ${interruption}`);
                }
                // 打开窗口
                setSearchAction(`打开职位详情: ${href}`);
                await api.event('job_detail_opened', `打开职位详情: ${href}`, 'script', 'info', { url: href });
                const detailResponse = this.broadcast.receive(this.targets.detail, this.bcTypes.GET_JOB_INFO, OPTIONS.jobInfoResponseTimeout);
                const opened = tools.openTabNSetTimestamp(href, this.targets.detail);
                setSearchAction(`等待详情页回传职位信息: ${href}`);
                await api.heartbeat('search', 'running', `等待详情页回传职位信息: ${href}`, {
                    ...scriptHeartbeatDetail(),
                    url: href,
                    detailWindowOpened: Boolean(opened),
                    jobInfoResponseTimeout: OPTIONS.jobInfoResponseTimeout,
                });
                // 接收职位信息
                let info;
                if (!opened) {
                    detailResponse.catch(() => null);
                    const popupError = new Error('浏览器拦截了职位详情页弹窗');
                    await api.event('job_detail_popup_blocked', `${popupError.message}: ${href}`, 'script', 'error', { url: href });
                    info = await fetchJobInfoFallback(href, popupError);
                } else try {
                    info = await detailResponse;
                } catch (e) {
                    if (tools.isManualInterruptionError(e)) throw e;
                    await api.event(
                        'job_detail_timeout',
                        `详情页未回传职位信息: ${href}`,
                        'script',
                        'error',
                        { url: href, error: String(e), hint: '请确认详情页是否出现 detail / running 心跳；新版脚本会在窗口名匹配时继续回传，不再受 15 秒加载限制' }
                    );
                    info = await fetchJobInfoFallback(href, e);
                }
                if (info && info.manual_intervention) {
                    throw new Error(`需要人工处理: ${info.reason || info.error || '详情页人工校验'}`);
                }
                if (!info || !info.title || !info.detail) {
                    throw new Error('职位详情缺少标题或描述');
                }
                await api.event('job_detail_received', `已读取职位详情: ${info.title}`, 'script', 'info', info);
                return info;
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
                    const interruption = tools.detectInterruptionText(interruptionText);
                    if (interruption) throw new Error(`需要人工处理: ${interruption}`);
                    const info = extractJobInfoFromDocument(doc, href, 'fetch_fallback');
                    if (!info.title || !info.detail) {
                        throw new Error('详情页 fetch 兜底解析失败：缺少标题或描述');
                    }
                    await api.event('job_detail_fetch_fallback_finished', `详情页兜底解析成功: ${info.title}`, 'script', 'info', {
                        url: href,
                        hasAddUrl: Boolean(info.addUrl),
                        hasChatUrl: Boolean(info.chatUrl),
                    });
                    return info;
                } catch (fallbackError) {
                    if (tools.isManualInterruptionError(fallbackError)) {
                        await api.event('job_detail_manual_intervention', `详情页需要人工校验: ${fallbackError}`, 'script', 'error', {
                            url: href,
                            originalError: String(originalError),
                        });
                        throw fallbackError;
                    }
                    await api.event('job_detail_fetch_fallback_failed', `详情页兜底解析失败: ${fallbackError}`, 'script', 'error', { url: href, originalError: String(originalError) });
                    throw new Error(`详情页广播失败且兜底解析失败: ${originalError}; ${fallbackError}`);
                }
            };

            const getJobInfoWithRetry = async (href) => {
                try {
                    return await getJobInfo(href);
                } catch (firstError) {
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

            const openGreetingChat = async (jobInfo, href, reason) => {
                if (!jobInfo.chatUrl) throw new Error('缺少聊天页地址');
                startGreetingWait(jobInfo);
                localStorage.setItem('__chatbot_zhou_greet_context', JSON.stringify({
                    url: href,
                    title: jobInfo.title,
                    company: jobInfo.company || '',
                    salary: jobInfo.salary || '',
                    greeting: this.introduce,
                    reason,
                }));
                await api.event('greet_chat_opened', `打开聊天页准备打招呼: ${jobInfo.title}`, 'script', 'info', {
                    title: jobInfo.title,
                    chatUrl: jobInfo.chatUrl,
                    reason,
                });
                const opened = tools.openTabNSetTimestamp(jobInfo.chatUrl, this.targets.chatGreet);
                if (!opened) {
                    finishGreetingWait();
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
                    await api.event('already_contacted', `${reason}: ${jobInfo.title}`, 'script', 'info', {
                        title: jobInfo.title,
                        url: href,
                        reason,
                    });
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
                        if (redirectedChatUrl) {
                            jobInfo.chatUrl = redirectedChatUrl;
                        }
                    } else {
                        await api.event('greet_entry_skipped', '详情页没有独立打招呼入口，直接打开聊天页', 'script', 'info', { title: jobInfo.title, chatUrl: jobInfo.chatUrl });
                    }
                    await openGreetingChat(jobInfo, href, '入口请求成功或已有聊天页地址');
                } catch (e) {
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
                    // 要自我介绍
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
                    // 告知结果
                    if (data.success) {
                        const count = Number(data.sessionGreetCount || tools.getSessionGreetCount());
                        logger.add(`打招呼成功，本轮计数 ${count}/${OPTIONS.sessionGreetLimit}`);
                    }
                    // 出错了
                    else {
                        logger.add(`打招呼失败${data.error ? ': ' + data.error : ''}`);
                    }
                    finishGreetingWait();
                    finishJobProgress(data.success ? '打招呼成功' : '打招呼失败');
                    if (!data.success && data.error && tools.isManualInterruptionError(data.error)) {
                        await handleManualInterruption(tools.manualInterruptionReason(data.error), 'chat_greet');
                        return;
                    }
                    if (data.success && isSessionLimitReached()) {
                        await stopForSessionLimit(Number(data.sessionGreetCount || tools.getSessionGreetCount()));
                        return;
                    }
                    loop();
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

            // 聊天页监听
            const chatListener = () => {
                this.broadcast.on(this.bcTypes.RUN, async (from, data) => {
                    if (from !== this.targets.chat) return;
                    if (data) {
                        logger.divider();
                        const hasNext = await nextPage();
                        if (!hasNext) return;
                        loop();
                    } else {
                        logger.add(`附件请求检查出错，已跳过自动聊天处理`);
                        await api.event('chat_attachment_check_failed', '附件请求检查出错，未重新打开聊天页', 'script', 'error');
                    }
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

            // 循环
            const loop = async () => {
                if (loopRunning) return;
                loopRunning = true;
                try {
                    if (waitingForGreeting) return;
                    const interruption = tools.detectManualInterruption();
                    if (interruption) {
                        await handleManualInterruption(interruption, 'search');
                        return;
                    }
                    // 如果暂停，则跳过
                    if (this.pause) {
                        logger.add('暂停中...');
                        return;
                    }
                    if (!(await ensureSessionLimitAvailable())) {
                        return;
                    }
                    logger.divider();
                    // 判断职位链接是否为空
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
                    // 抽取第一个
                    const href = jobHrefs.shift();
                    seenJobHrefs.add(href);
                    beginJobProgress(href);
                    // 获取详情
                    logger.add(`正在获取职位详情`);
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
                    // 如果聊过，下一个
                    if (jobInfo.talked) {
                        const reason = jobInfo.talked_reason || '页面显示已沟通';
                        logger.add(`职位 [${jobInfo.title}] ${reason}，下一个`);
                        await api.createAction('already_contacted', { reason }, jobInfo, 'completed');
                        await api.event('decision_skip', `跳过已沟通职位: ${jobInfo.title}`, 'script', 'info', { title: jobInfo.title, url: href, reason });
                        finishJobProgress('已沟通跳过');
                        setTimeout(loop, 0);
                        return;
                    }
                    // 否则发送消息计算匹配度
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
                    if (analysis.match_reason) {
                        logger.add(`判断原因: ${analysis.match_reason}`);
                    }
                    if (analysis.recommendation) {
                        logger.add(`推荐动作: ${analysis.recommendation}`);
                    }
                    await api.event('job_analysis_finished', `职位分析完成: ${jobInfo.title} / ${score}`, 'script', 'info', { title: jobInfo.title, score, recommendation: analysis.recommendation, risks: analysis.risks || [] });
                    if (analysis.risks && analysis.risks.length) {
                        logger.add(`风险点: ${analysis.risks.join('；')}`);
                    }
                    if (!(await syncControlFromBackend(`暂停检查: 职位分析完成 ${jobInfo.title}`))) {
                        finishJobProgress('暂停停止');
                        return;
                    }
                    // 如果分数达到阈值，打个招呼
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
                    }
                    // 否则下一轮
                    else {
                        if (analysis.recommendation === 'wait_for_confirm') {
                            await recordGreetingSuggestion(jobInfo, analysis, href, analysis.match_reason || '模型建议人工确认，不自动打招呼');
                        } else {
                            await api.event('decision_skip', `跳过职位: ${jobInfo.title} / ${score}`, 'script', 'info', { title: jobInfo.title, score, recommendation: analysis.recommendation, reason: analysis.match_reason || analysis.blocked_reason || '' });
                        }
                        finishJobProgress('跳过');
                        setTimeout(loop, 0);
                    }
                } catch (e) {
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
                    booting = true;
                    started = true;
                    resetProgress();
                    if (!tools.getGreetSession().runId || tools.getGreetSession().ended) {
                        beginGreetSession('开始新一轮');
                    }
                    setSearchAction('程序启动，读取配置');
                    logger.add('--程序启动--');
                    await api.heartbeat('search', 'running', '程序启动');
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

            // 获取职位信息
            const getJobInfo = async () => {
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
                            await api.event('broadcast_send_failed', `详情页人工校验回传失败: ${sendError}`, 'script', 'error', {
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
            const sendMsg = (text) => {
                return new Promise(async (resolve, reject) => {
                    try {
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
                        btn.click();
                        await tools.asyncSleep(500);
                        await pageApi.event('message_send_finished', '消息已点击发送', 'script', 'info', {
                            button: tools.elementBrief(btn),
                            input: tools.elementBrief(ipt),
                            length: String(text).length,
                        });
                        resolve();
                    } catch (e) {
                        await pageApi.event('message_send_failed', `消息发送失败: ${e}`, 'script', 'error', e.detail || {});
                        reject(e);
                    }
                })
            };

            // 打招呼
            const sayHi = async () => {
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
                    const introduce = (await this.broadcast.sendAndReceive(this.targets.search, this.bcTypes.SAY_HI)).introduce;
                    if (!introduce) throw new Error('未启用打招呼用语');
                    await tools.actionSleep();
                    await sendMsg(introduce);
                    let greetContext = {};
                    try {
                        greetContext = JSON.parse(localStorage.getItem('__chatbot_zhou_greet_context') || '{}');
                    } catch (e) {
                        greetContext = {};
                    }
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
                        { sessionGreetCount, runId: tools.getGreetSession().runId }
                    );
                    heartbeatActive = false;
                    this.broadcast.send(this.targets.search, this.bcTypes.SAY_HI, { success: true, sessionGreetCount }).catch(async (sendError) => {
                        await pageApi.event('broadcast_send_failed', `打招呼结果回传失败: ${sendError}`, 'script', 'error');
                    }).finally(() => {
                        this.broadcast.destroy();
                        setTimeout(() => window.close(), 800);
                    });
                } catch (e) {
                    heartbeatActive = false;
                    await pageApi.heartbeat('chat_greet', 'error', String(e));
                    await pageApi.event('greet_failed', `打招呼失败: ${e}`, 'script', 'error');
                    this.broadcast.send(this.targets.search, this.bcTypes.SAY_HI, { success: false, error: String(e) }).catch(async (sendError) => {
                        await pageApi.event('broadcast_send_failed', `打招呼失败结果回传失败: ${sendError}`, 'script', 'error');
                    }).finally(() => {
                        this.broadcast.destroy();
                        setTimeout(() => window.close(), 800);
                    });
                }
            };

            // 获取聊天记录信息
            const getChatInfo = async () => {
                const ctn = await tools.endlessFind(SELECTORS.ZHIPIN.CHAT.HISTORYCTN);

                const getMsgs = async () => {
                    const lis = Array.from(ctn.querySelectorAll(SELECTORS.ZHIPIN.CHAT.USEFULMSG));
                    // 提取历史记录
                    const msgs = [];
                    lis.forEach(li => {
                        const role = li.classList.contains('item-friend') ? 'user' : 'assistant';
                        const msgBox = li.querySelector(SELECTORS.ZHIPIN.CHAT.MSGCONTENT);
                        if (!msgBox) return;
                        msgs.push({
                            role,
                            content: msgBox.innerText,
                        });
                    });
                    // 只识别 BOSS 官方附件简历请求卡片。
                    let needResume = 0;
                    let resumeSended = false;
                    let confirmAddr = false;
                    let resumeRequestCard = null;
                    // 判断是否有过明确弹窗
                    const rlis = lis.reverse();
                    for (const li of rlis) {
                        if (li.classList.contains('item-myself')) {
                            break;
                        }
                        const bossGreen = li.querySelector('.boss-green');
                        const dialog = li.querySelector('.item-dialog');
                        if (bossGreen) {
                            const t = bossGreen.innerText;
                            if (t.includes('附件简历') && t.includes('是否同意') && t.includes('同意')) {
                                needResume = 2;
                                resumeRequestCard = li;
                            }
                        } else if (dialog) {
                            const t = dialog.querySelector('.msg-dialog-title').innerText;
                            if (t.indexOf('您是否接受此工作地点?') !== -1) {
                                confirmAddr = true;
                            }
                        }
                    }
                    // 判断是否发过简历
                    const bossGreen = ctn.querySelectorAll('.boss-green');
                    if (bossGreen.length) {
                        bossGreen.forEach(el => {
                            const t = el.innerText;
                            if (t.indexOf('点击预览附件简历') !== -1) {
                                resumeSended = true;
                            }
                        });
                    }
                    return {
                        msgs,
                        needResume,
                        resumeSended,
                        confirmAddr,
                        resumeRequestCard,
                        talked: !msgs.every(d => d.role === 'user'),
                        jobEl: (await tools.endlessFind(SELECTORS.ZHIPIN.CHAT.JOBEL)).querySelector(SELECTORS.ZHIPIN.CHAT.JOBCITY)
                    };
                };

                const scroll2Top = async () => {
                    if (ctn.scrollTop === 0) return;
                    ctn.scrollTop = 0;
                    await tools.asyncSleep(300);
                    await scroll2Top();
                };

                // 滚动到顶部
                await tools.asyncSleep(300);
                await scroll2Top();
                // 获取聊天记录
                return await getMsgs();
            };

            // 发送简历
            const sendResume = async (context = {}, requestCard = null) => {
                await pageApi.event('attachment_auto_send_started', 'BOSS 官方卡片请求简历，自动发送附件简历', 'script', 'info', context);
                if (requestCard) {
                    const agreeButton = Array.from(requestCard.querySelectorAll('button, a, span, div'))
                        .find(el => String(el.innerText || el.textContent || '').trim() === '同意');
                    if (agreeButton) {
                        const clickable = agreeButton.closest('button, a') || agreeButton;
                        clickable.click();
                        await tools.actionSleep(800);
                        await pageApi.createAction('send_resume', {
                            reason: 'BOSS 官方卡片请求简历，已点击同意',
                            context,
                        }, context, 'completed');
                        await pageApi.event('attachment_sent', '已通过官方卡片同意发送简历', 'script', 'info', context);
                        return;
                    }
                }
                await pageApi.createAction('send_resume_suggestion', {
                    reason: '未找到 BOSS 官方简历请求卡片内的同意按钮，未执行发送',
                    context,
                }, context, 'completed');
                await pageApi.event('attachment_send_skipped', '官方简历请求卡片识别失败，未点击聊天工具栏简历按钮', 'script', 'error', context);
                status('未找到官方卡片同意按钮，已跳过简历发送');
            };

            let logger = null;
            // 给搜索页同步状态
            const status = (text) => {
                logger && logger.add(text);
                pageApi.heartbeat('chat', 'running', text).catch(() => null);
                this.broadcast && this.broadcast.send(
                    this.targets.search,
                    this.bcTypes.STATUS,
                    text
                ).catch(() => null);
            };
            // 聊天
            const chat = async () => {
                // 开始广播
                startBroadcast(this.targets.chat);
                // 心跳
                let heartbeatActive = true;
                const loop = async () => {
                    if (!heartbeatActive || !this.broadcast) return;
                    const backendStatus = await pageApi.heartbeat('chat', 'running', '附件请求监听');
                    applyBackendConfig(backendStatus.config);
                    if (backendStatus.control === 'paused' || backendStatus.control === 'stopped') {
                        status('CLI 已暂停附件监听');
                        heartbeatActive = false;
                        return;
                    }
                    setTimeout(loop, 1000);
                };
                loop();

                const backendStatus = await pageApi.heartbeat('chat', 'running', '检查当前聊天页官方简历请求卡片');
                applyBackendConfig(backendStatus.config);
                await pageApi.event('chat_attachment_check_started', '检查当前聊天页官方简历请求卡片', 'script');
                if (backendStatus.control === 'paused' || backendStatus.control === 'stopped') {
                    status('CLI 已暂停附件监听');
                    heartbeatActive = false;
                    return;
                }
                try {
                    const chatInfo = await getChatInfo();
                    const title = chatInfo.jobEl ? chatInfo.jobEl.innerText : document.title;
                    if (chatInfo.needResume === 2 && !chatInfo.resumeSended) {
                        status('检测到 BOSS 官方简历请求卡片，自动发送简历附件');
                        await sendResume({ title }, chatInfo.resumeRequestCard);
                        status('简历附件处理完成');
                    } else {
                        await pageApi.event('chat_attachment_noop', '当前聊天页未发现官方简历请求卡片，跳过', 'script', 'info', {
                            title,
                        });
                    }
                } catch (e) {
                    status('检查当前聊天页附件请求出错');
                    await pageApi.event('chat_attachment_check_failed', `检查当前聊天页附件请求出错: ${e}`, 'script', 'error');
                } finally {
                    heartbeatActive = false;
                }
            };

            // 主函数
            const main = async () => {
                // 判断来源
                const now = new Date().getTime();
                const isGreet = now - tools.getTimestamp(this.targets.chatGreet) < OPTIONS.timestampTimeout && window.name === this.targets.chatGreet;

                if (isGreet) {
                    sayHi();
                }
                else {
                    // 日志
                    logger = new Logger();
                    logger.runBtn.remove();
                    logger.clearBtn.remove();
                    // 等待加载
                    await tools.asyncSleep(3000);
                    chat()
                        .then(async () => {
                            status('附件请求检查完毕');
                            await this.broadcast.send(this.targets.search, this.bcTypes.RUN, true);
                        })
                        .catch(async () => {
                            status('附件请求检查出错');
                            await this.broadcast.send(this.targets.search, this.bcTypes.RUN, false);
                        }).finally(() => {
                            this.broadcast.destroy();
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
