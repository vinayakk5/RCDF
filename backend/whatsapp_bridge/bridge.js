/**
 * 100% Free Self-Hosted WhatsApp Web Multi-Device Bridge for RCDF Operations
 * Multi-Session Architecture (3 Accounts Simultaneously):
 *   - wa_1: Shree Nath Industries
 *   - wa_2: Shree Vinayak Trading Company
 *   - wa_3: Shree Ganpati Enterprises
 * Powered by @whiskeysockets/baileys
 */
const crypto = require('crypto');
if (!globalThis.crypto) globalThis.crypto = crypto.webcrypto || crypto;
if (!global.crypto) global.crypto = crypto.webcrypto || crypto;

// Guard against unhandled promise rejections from Baileys socket closures (e.g. code 1006)
process.on('unhandledRejection', (reason, promise) => {
    console.warn('[Bridge] Handled unhandledRejection:', reason?.message || reason);
});
process.on('uncaughtException', (err) => {
    console.error('[Bridge] Handled uncaughtException:', err?.message || err);
});

const express = require('express');
const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    Browsers,
    downloadMediaMessage,
    isJidGroup,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const QRCode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');
const axios = require('axios');
const path = require('path');
const fs = require('fs');
const pino = require('pino');

// Environment & Configuration
const PORT = parseInt(process.env.WHATSAPP_PORT || '3001', 10);
const FASTAPI_WEBHOOK_URL = process.env.FASTAPI_WEBHOOK_URL || 'http://127.0.0.1:8000/api/whatsapp/webhook';
const UPLOAD_DIR = path.resolve(__dirname, '../uploads/whatsapp');

if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

// Bill & Financial keywords for filtering out personal/spam chit-chat
const BILL_KEYWORDS_REGEX = /\b(bill|invoice|challan|bilty|bilti|weight|kanta|slip|unloading|domc|mustard|oil|cattle|feed|rcdf|dispatch|rate|qtl|mt|truck|rj\d|po|tender)\b/i;

// 3 Registered Corporate Sessions
const SESSION_DEFINITIONS = [
    {
        id: 'wa_1',
        name: 'Shree Nath Industries',
        dirName: fs.existsSync(path.resolve(__dirname, 'auth_baileys_session')) ? 'auth_baileys_session' : 'auth_baileys_wa_1'
    },
    {
        id: 'wa_2',
        name: 'Shree Vinayak Trading Company',
        dirName: 'auth_baileys_wa_2'
    },
    {
        id: 'wa_3',
        name: 'Shree Ganpati Enterprises',
        dirName: 'auth_baileys_wa_3'
    }
];

class WhatsAppSession {
    constructor(def) {
        this.id = def.id;
        this.displayName = def.name;
        this.authDir = path.resolve(__dirname, def.dirName);
        this.sock = null;
        this.currentQR = null;
        this.currentQRDataUrl = null;
        this.connectionStatus = 'disconnected';
        this.userInfo = null;
        this.whitelistJids = new Set();
        this.knownChats = new Map();
        this.isInitializing = false;
        this.reconnectTimer = null;
    }

    registerChat(jid, name, isGroup) {
        if (!jid || jid.endsWith('@newsletter') || jid.endsWith('@broadcast') || jid.includes('status@broadcast')) return;
        const existing = this.knownChats.get(jid) || {};
        this.knownChats.set(jid, {
            id: jid,
            name: name || existing.name || (isGroup ? 'Group Chat' : jid.split('@')[0]),
            subject: name || existing.subject || (isGroup ? 'Group Chat' : jid.split('@')[0]),
            is_group: isGroup !== undefined ? isGroup : (isJidGroup(jid) || existing.is_group || false),
            last_active: Date.now()
        });
    }

    async init() {
        if (this.isInitializing) return;
        this.isInitializing = true;
        this.connectionStatus = 'connecting';
        this.currentQR = null;
        this.currentQRDataUrl = null;

        try {
            console.log(`[${this.id}] Initializing session: ${this.displayName} (${this.authDir})`);
            const { state, saveCreds } = await useMultiFileAuthState(this.authDir);
            const { version, isLatest } = await fetchLatestBaileysVersion();
            console.log(`[${this.id}] WA Web v${version.join('.')}, isLatest: ${isLatest}`);

            this.sock = makeWASocket({
                logger: pino({ level: 'silent' }),
                printQRInTerminal: false,
                version,
                auth: state,
                browser: Browsers.macOS(`Desktop-${this.id}`),
                connectTimeoutMs: 60000,
                syncFullHistory: false
            });

            this.sock.ev.on('creds.update', saveCreds);

            this.sock.ev.on('connection.update', async (update) => {
                const { connection, lastDisconnect, qr } = update;

                if (qr) {
                    this.currentQR = qr;
                    try {
                        this.currentQRDataUrl = await QRCode.toDataURL(qr, { margin: 2, scale: 6 });
                    } catch (err) {
                        console.error(`[${this.id}] Error generating QR Data URL:`, err.message);
                    }
                    this.connectionStatus = 'qr_ready';
                    console.log(`\n========================================`);
                    console.log(`>>> [${this.id}] ${this.displayName} QR READY <<<`);
                    console.log(`========================================`);
                    qrcodeTerminal.generate(qr, { small: true });
                }

                if (connection === 'open') {
                    this.connectionStatus = 'connected';
                    this.currentQR = null;
                    this.currentQRDataUrl = null;
                    const rawId = this.sock.user?.id || '';
                    const phone = rawId.split(':')[0] || rawId.split('@')[0];
                    this.userInfo = {
                        id: phone + '@s.whatsapp.net',
                        name: this.sock.user?.name || this.displayName,
                        phone: phone
                    };
                    console.log(`[${this.id}] Connected Live: ${this.userInfo.name} (${this.userInfo.phone})`);
                }

                if (connection === 'close') {
                    const statusCode = (lastDisconnect?.error)?.output?.statusCode;
                    const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
                    console.log(`[${this.id}] Connection closed. Reason: ${lastDisconnect?.error?.message || statusCode}, Reconnecting: ${shouldReconnect}`);
                    this.connectionStatus = 'disconnected';
                    this.userInfo = null;
                    this.isInitializing = false;

                    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

                    if (shouldReconnect) {
                        this.reconnectTimer = setTimeout(() => {
                            this.init().catch(err => console.error(`[${this.id}] Reconnect error:`, err?.message || err));
                        }, 5000);
                    } else {
                        console.log(`[${this.id}] Logged out. Clearing auth credentials to request new QR.`);
                        if (fs.existsSync(this.authDir)) fs.rmSync(this.authDir, { recursive: true, force: true });
                        this.reconnectTimer = setTimeout(() => {
                            this.init().catch(err => console.error(`[${this.id}] Re-init error:`, err?.message || err));
                        }, 5000);
                    }
                }
            });

            this.sock.ev.on('contacts.upsert', (contacts) => {
                for (const contact of contacts) {
                    this.registerChat(contact.id, contact.name || contact.notify || contact.verifiedName, isJidGroup(contact.id));
                }
            });

            this.sock.ev.on('messages.upsert', async (m) => {
                // Strictly process unseen/newly notified incoming messages
                if (m.type !== 'notify') return;

                for (const msg of m.messages) {
                    if (!msg.message || msg.key.fromMe) continue;

                    const jid = msg.key.remoteJid;
                    if (!jid || jid === 'status@broadcast' || jid.endsWith('@newsletter') || jid.endsWith('@broadcast')) continue;

                    const isGroup = isJidGroup(jid);
                    const sender = isGroup ? (msg.key.participant || jid) : jid;
                    const pushName = msg.pushName || 'Unknown';

                    this.registerChat(jid, pushName, isGroup);
                    if (isGroup) this.registerChat(sender, pushName, false);

                    const messageType = Object.keys(msg.message || {})[0];
                    const messageContent = msg.message?.[messageType];

                    let text = '';
                    if (messageType === 'conversation') text = msg.message.conversation || '';
                    else if (messageType === 'extendedTextMessage') text = msg.message.extendedTextMessage?.text || '';
                    else if (messageType === 'imageMessage') text = msg.message.imageMessage?.caption || '';
                    else if (messageType === 'documentMessage') text = msg.message.documentMessage?.caption || '';

                    const hasMedia = ['imageMessage', 'videoMessage', 'documentMessage', 'audioMessage'].includes(messageType);

                    // Whitelist filtering: If whitelist is configured, allow if contact is whitelisted OR message has bill media/keywords
                    if (this.whitelistJids.size > 0 && !this.whitelistJids.has(jid) && !this.whitelistJids.has(sender)) {
                        if (!hasMedia && !BILL_KEYWORDS_REGEX.test(text)) {
                            console.log(`[${this.id} Whitelist Skip] Non-whitelisted contact without bill/media: ${sender} / ${jid}`);
                            continue;
                        }
                    }

                    // Chit-chat & spam filter: If no media and text does not mention any bill/weight keywords, ignore
                    if (!hasMedia && !BILL_KEYWORDS_REGEX.test(text)) {
                        console.log(`[${this.id} Spam Skip] Ignored non-bill chit-chat from ${sender}: "${text.substring(0, 40)}"`);
                        continue;
                    }

                    console.log(`[${this.id} Incoming Message] From: ${sender} | Chat: ${jid} | Type: ${messageType}`);

                    let fileInfo = null;
                    if (hasMedia) {
                        try {
                            const buffer = await downloadMediaMessage(msg, 'buffer', {}, { logger: pino({ level: 'silent' }) });
                            if (buffer) {
                                const mime = messageContent?.mimetype || 'application/octet-stream';
                                let ext = mime.split('/')[1]?.split(';')[0]?.toLowerCase() || 'bin';
                                if (ext === 'jpeg') ext = 'jpg';
                                const safeFilename = `wa_${this.id}_${Date.now()}_${msg.key.id.substring(0, 8)}.${ext}`;
                                const savePath = path.join(UPLOAD_DIR, safeFilename);

                                fs.writeFileSync(savePath, buffer);
                                fileInfo = {
                                    filename: safeFilename,
                                    path: savePath,
                                    mimetype: mime,
                                    filesize: buffer.length
                                };
                                console.log(`[${this.id} Attachment Saved] ${savePath} (${mime}, size=${buffer.length})`);
                            }
                        } catch (err) {
                            console.error(`[${this.id} Attachment Failed] Media download failed:`, err.message);
                        }
                    }

                    const payload = {
                        session_id: this.id,
                        company_name: this.displayName,
                        message_id: msg.key.id,
                        timestamp: msg.messageTimestamp,
                        from_jid: jid,
                        sender_phone: sender.split('@')[0],
                        sender_name: pushName,
                        is_group: isGroup,
                        group_name: isGroup ? (this.knownChats.get(jid)?.name || jid) : null,
                        text: text,
                        has_media: !!fileInfo,
                        media: fileInfo
                    };

                    try {
                        const response = await axios.post(FASTAPI_WEBHOOK_URL, payload, { timeout: 30000 });
                        console.log(`[${this.id}] FastAPI webhook accepted message: ${payload.message_id}`);

                        if (response.data && response.data.reply_text && this.sock) {
                            await this.sock.sendMessage(jid, { text: response.data.reply_text }, { quoted: msg });
                            console.log(`[${this.id}] Sent auto-reply to ${jid}`);
                        }
                    } catch (whErr) {
                        console.error(`[${this.id}] FastAPI webhook call failed:`, whErr.message);
                    }
                }
            });

        } catch (initErr) {
            console.error(`[${this.id}] Initialization error:`, initErr.message);
        } finally {
            this.isInitializing = false;
        }
    }
}

// Instantiate All 3 Sessions
const sessions = new Map();
for (const def of SESSION_DEFINITIONS) {
    sessions.set(def.id, new WhatsAppSession(def));
}

function getSession(req) {
    const sId = req.query.session || req.params.sessionId || req.body?.session_id;
    if (sId && sessions.has(sId)) {
        return sessions.get(sId);
    }
    // Default to wa_1
    return sessions.get('wa_1');
}

// -------------------------------------------------------------
// Express REST API
// -------------------------------------------------------------
const app = express();
app.use(express.json({ limit: '50mb' }));

app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    if (req.method === 'OPTIONS') return res.sendStatus(200);
    next();
});

// Overall & Per-Session Status
app.get('/status', (req, res) => {
    const s = getSession(req);
    const sessionList = {};
    let totalConnected = 0;

    for (const [id, sess] of sessions.entries()) {
        sessionList[id] = {
            id,
            name: sess.displayName,
            status: sess.connectionStatus,
            connected: sess.connectionStatus === 'connected',
            user: sess.userInfo,
            has_qr: !!sess.currentQRDataUrl,
            whitelist_count: sess.whitelistJids.size
        };
        if (sess.connectionStatus === 'connected') totalConnected++;
    }

    // Return backwards-compatible top-level properties based on primary or requested session
    res.json({
        success: true,
        session_id: s.id,
        status: s.connectionStatus,
        connected: s.connectionStatus === 'connected',
        user: s.userInfo,
        has_qr: !!s.currentQRDataUrl,
        whitelist_count: s.whitelistJids.size,
        total_sessions: sessions.size,
        connected_sessions: totalConnected,
        sessions: sessionList
    });
});

// QR Code for requested session (or first session requiring QR)
app.get(['/qr', '/qr/:sessionId'], (req, res) => {
    let s = getSession(req);
    // If specific session requested wasn't qr_ready, find any session that is qr_ready
    if (!req.query.session && !req.params.sessionId && s.connectionStatus !== 'qr_ready') {
        for (const sess of sessions.values()) {
            if (sess.connectionStatus === 'qr_ready' && sess.currentQRDataUrl) {
                s = sess;
                break;
            }
        }
    }

    if (s.connectionStatus === 'connected') {
        return res.json({ success: true, session_id: s.id, connected: true, qr: null, qr_data_url: null });
    }
    if (!s.currentQRDataUrl) {
        return res.json({ success: false, session_id: s.id, connected: false, error: `QR not ready yet for ${s.displayName}` });
    }
    res.json({
        success: true,
        session_id: s.id,
        connected: false,
        qr: s.currentQR,
        qr_data_url: s.currentQRDataUrl
    });
});

// Chats & Groups
app.get(['/chats', '/groups', '/chats/:sessionId', '/groups/:sessionId'], (req, res) => {
    const s = getSession(req);
    const cached = Array.from(s.knownChats.values()).map(c => ({
        ...c,
        session_id: s.id,
        is_monitored: s.whitelistJids.has(c.id)
    }));
    res.json({ success: true, session_id: s.id, chats: cached, groups: cached, source: 'cache' });
});

app.delete(['/chats/:jid', '/chats/:sessionId/:jid'], (req, res) => {
    const s = getSession(req);
    const jid = req.params.jid;
    if (jid) {
        s.knownChats.delete(jid);
        s.whitelistJids.delete(jid);
        console.log(`[${s.id}] Removed chat: ${jid}`);
    }
    res.json({ success: true, session_id: s.id, message: `Removed ${jid}` });
});

app.post('/send', async (req, res) => {
    const s = getSession(req);
    let { jid, text } = req.body || {};
    if (!jid || !text) return res.status(400).json({ success: false, error: 'jid and text are required' });
    if (s.connectionStatus !== 'connected' || !s.sock) {
        return res.status(503).json({ success: false, session_id: s.id, error: `WhatsApp session ${s.displayName} not connected` });
    }

    if (!jid.includes('@')) {
        const digits = jid.replace(/\D/g, '');
        jid = digits.length === 10 ? `91${digits}@s.whatsapp.net` : `${digits}@s.whatsapp.net`;
    }
    try {
        await s.sock.sendMessage(jid, { text });
        res.json({ success: true, session_id: s.id, message: 'Message sent', jid });
    } catch (err) {
        res.status(500).json({ success: false, session_id: s.id, error: err.message });
    }
});

app.post(['/whitelist', '/whitelist/:sessionId'], (req, res) => {
    const s = getSession(req);
    const { jids, monitored_groups } = req.body || {};
    s.whitelistJids.clear();
    if (Array.isArray(jids)) {
        jids.forEach(j => { if (j && !j.endsWith('@newsletter') && !j.endsWith('@broadcast')) s.whitelistJids.add(j); });
    }
    if (Array.isArray(monitored_groups)) {
        monitored_groups.forEach(g => {
            if (g && g.id && !g.id.endsWith('@newsletter') && !g.id.endsWith('@broadcast')) {
                s.registerChat(g.id, g.subject || g.name, g.is_group || g.id.endsWith('@g.us'));
            }
        });
    }
    console.log(`[${s.id}] Updated whitelist: ${s.whitelistJids.size} channels active.`);
    res.json({ success: true, session_id: s.id, whitelisted: s.whitelistJids.size });
});

app.post(['/reconnect', '/reconnect/:sessionId'], async (req, res) => {
    const s = getSession(req);
    res.json({ success: true, session_id: s.id, message: `Reconnect initiated for ${s.displayName}` });
    if (s.sock) s.sock.end();
    s.isInitializing = false;
    setTimeout(() => s.init(), 500);
});

app.post(['/logout', '/logout/:sessionId'], async (req, res) => {
    const s = getSession(req);
    try {
        if (s.sock) {
            await s.sock.logout();
        }
        res.json({ success: true, session_id: s.id, message: `Logged out ${s.displayName}` });
    } catch (err) {
        res.status(500).json({ success: false, session_id: s.id, error: err.message });
    }
});

// Boot all 3 sessions
app.listen(PORT, '0.0.0.0', () => {
    console.log(`=== Multi-Session WhatsApp Bridge Running on http://0.0.0.0:${PORT} ===`);
    for (const sess of sessions.values()) {
        sess.init().catch(err => console.error(`[${sess.id}] Boot error:`, err?.message || err));
    }
});
