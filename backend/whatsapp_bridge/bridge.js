/**
 * 100% Free Self-Hosted WhatsApp Web Multi-Device Bridge for RCDF Operations
 * Powered by whatsapp-web.js & Chromium
 */
const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');
const axios = require('axios');
const path = require('path');
const fs = require('fs');

// Environment & Configuration
const PORT = parseInt(process.env.WHATSAPP_PORT || '3001', 10);
const FASTAPI_WEBHOOK_URL = process.env.FASTAPI_WEBHOOK_URL || 'http://127.0.0.1:8000/api/whatsapp/webhook';
const AUTH_DIR = path.resolve(__dirname, 'auth_wweb_session');
const UPLOAD_DIR = path.resolve(__dirname, '../uploads/whatsapp');

if (!fs.existsSync(UPLOAD_DIR)) {
    fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

// Global State
let client = null;
let currentQR = null;
let currentQRDataUrl = null;
let connectionStatus = 'disconnected'; // 'disconnected' | 'connecting' | 'qr_ready' | 'authenticated' | 'connected'
let userInfo = null;
let whitelistJids = new Set();
let isInitializing = false;

console.log('--- Initializing RCDF WhatsApp Bridge (whatsapp-web.js) ---');

/**
 * Initialize WhatsApp Client
 */
async function initializeWhatsAppClient() {
    if (isInitializing) return;
    isInitializing = true;
    connectionStatus = 'connecting';
    currentQR = null;
    currentQRDataUrl = null;

    if (client) {
        try {
            await client.destroy();
        } catch (e) {}
    }

    client = new Client({
        authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        }
    });

    client.on('qr', async (qr) => {
        currentQR = qr;
        try {
            currentQRDataUrl = await QRCode.toDataURL(qr, { margin: 2, scale: 6 });
        } catch (err) {
            console.error('Error generating QR Data URL:', err.message);
        }
        connectionStatus = 'qr_ready';
        console.log('\n========================================');
        console.log('>>> OFFICIAL WHATSAPP QR READY TO SCAN <<<');
        console.log('========================================');
        qrcodeTerminal.generate(qr, { small: true });
    });

    client.on('authenticated', () => {
        connectionStatus = 'authenticated';
        console.log('WhatsApp client authenticated successfully.');
    });

    client.on('ready', async () => {
        connectionStatus = 'connected';
        currentQR = null;
        currentQRDataUrl = null;
        isInitializing = false;

        const info = client.info;
        userInfo = {
            id: info?.wid?._serialized || '',
            name: info?.pushname || 'RCDF Account',
            phone: info?.wid?.user || ''
        };
        console.log(`WhatsApp Bridge Connected Live: ${userInfo.name} (${userInfo.phone})`);

        // Warm the knownChats cache — read directly from WAWebCollections to avoid getChatModel() errors
        const warmCache = async (attempt) => {
            if (attempt > 4) {
                console.warn('[Cache Warm] Giving up after 4 attempts. Cache will fill as messages arrive.');
                return;
            }
            try {
                console.log(`[Cache Warm] Attempt ${attempt}: Reading from WAWebCollections...`);
                const rawChats = await client.pupPage.evaluate(() => {
                    try {
                        const chatCol = window.require('WAWebCollections').Chat;
                        if (!chatCol) return [];
                        return chatCol.getModelsArray().map(c => {
                            try {
                                return {
                                    id: c.id && c.id._serialized ? c.id._serialized : String(c.id || ''),
                                    name: c.name || c.formattedTitle || (c.id && c.id.user) || '',
                                    isGroup: !!c.isGroup
                                };
                            } catch (e) { return null; }
                        }).filter(Boolean);
                    } catch (e) { return []; }
                });
                let count = 0;
                for (const chat of rawChats) {
                    const id = chat.id;
                    if (!id || id.endsWith('@newsletter') || id.endsWith('@broadcast') || id.includes('status@broadcast')) continue;
                    registerChat(id, chat.name, chat.isGroup);
                    count++;
                }
                console.log(`[Cache Warm] Loaded ${count} chats into cache successfully.`);
            } catch (e) {
                console.warn(`[Cache Warm] Attempt ${attempt} failed (${e?.message || e}). Retrying in 20s...`);
                setTimeout(() => warmCache(attempt + 1), 20000);
            }
        };
        setTimeout(() => warmCache(1), 10000); // 10s delay for WA to init
    });


    client.on('auth_failure', (msg) => {
        connectionStatus = 'disconnected';
        userInfo = null;
        isInitializing = false;
        console.error('WhatsApp authentication failure:', msg);
    });

    client.on('disconnected', (reason) => {
        connectionStatus = 'disconnected';
        currentQR = null;
        currentQRDataUrl = null;
        userInfo = null;
        isInitializing = false;
        console.warn(`WhatsApp client disconnected. Reason: ${reason}`);
        setTimeout(() => {
            initializeWhatsAppClient();
        }, 5000);
    });

    client.on('message_create', async (msg) => {
        // Handle incoming messages
        if (!msg.fromMe) {
            try {
                await handleIncomingMessage(msg);
            } catch (err) {
                console.error(`Error handling message: ${err.message}`);
            }
        }
    });

    try {
        await client.initialize();
    } catch (err) {
        isInitializing = false;
        console.error('Client initialization failed:', err.message);
    }
}

/**
 * Handle incoming WhatsApp message with document extraction
 */
async function handleIncomingMessage(msg) {
    const jid = msg.from;
    const isGroup = jid.endsWith('@g.us');
    const isNewsletter = jid.endsWith('@newsletter') || jid.endsWith('@broadcast') || jid === 'status@broadcast';
    const sender = msg.author || msg.from;

    // Ignore newsletters, broadcast channels, status stories, reactions, and system notifications
    if (isNewsletter || msg.type === 'e2e_notification' || msg.type === 'call_log' || msg.type === 'protocol' || msg.type === 'reaction') {
        return;
    }

    let chatName = msg._data?.notifyName || (isGroup ? 'WhatsApp Group' : jid.split('@')[0]);
    let chat = null;

    try {
        chat = await msg.getChat();
        if (chat && chat.name) chatName = chat.name;
    } catch (chatErr) {
        // Fallback without throwing
    }

    // Always register discovered chat/sender for UI monitoring (only real chats)
    registerChat(jid, chatName, isGroup);
    if (sender && sender !== jid && !sender.endsWith('@newsletter') && !sender.endsWith('@broadcast')) {
        registerChat(sender, msg._data?.notifyName, false);
    }

    // Check Whitelist if configured
    if (whitelistJids.size > 0 && !whitelistJids.has(jid) && !whitelistJids.has(sender)) {
        console.log(`[Whitelist Skip] Ignored message from non-whitelisted sender: ${sender} / ${jid}`);
        return; // Ignore messages from non-whitelisted chats
    }

    console.log(`[Incoming Message] From: ${sender} | Chat: ${chatName} | Type: ${msg.type}`);

    let fileInfo = null;
    if (msg.hasMedia) {
        for (let attempt = 1; attempt <= 3; attempt++) {
            try {
                if (attempt > 1) {
                    await new Promise(r => setTimeout(r, 800 * attempt));
                }
                const media = await msg.downloadMedia();
                if (media && media.data) {
                    const mime = media.mimetype || 'image/jpeg';
                    let ext = (mime.split('/')[1] || 'jpg').split(';')[0].toLowerCase();
                    if (ext === 'jpeg') ext = 'jpg';
                    if (ext === 'octet-stream' || ext === 'bin') ext = 'jpg';
                    const safeFilename = `wa_${Date.now()}_${msg.id.id.substring(0, 8)}.${ext}`;
                    const savePath = path.join(UPLOAD_DIR, safeFilename);

                    fs.writeFileSync(savePath, Buffer.from(media.data, 'base64'));
                    fileInfo = {
                        filename: safeFilename,
                        path: savePath,
                        mimetype: mime,
                        filesize: media.data.length
                    };
                    console.log(`[Attachment Saved] ${savePath} (${mime}, attempt ${attempt}, size=${media.data.length} b64chars)`);
                    break;
                } else {
                    console.warn(`[Attachment Download] Attempt ${attempt}: downloadMedia returned no data`);
                }
            } catch (mediaErr) {
                console.warn(`[Attachment Download] Attempt ${attempt} failed:`, mediaErr?.message || mediaErr);
            }
        }
        if (!fileInfo) {
            console.error(`[Attachment Failed] Could not download media for message ${msg.id.id} from ${sender}`);
        }
    }

    // Prepare Webhook Payload for FastAPI
    const payload = {
        message_id: msg.id.id,
        timestamp: msg.timestamp || Math.floor(Date.now() / 1000),
        from_jid: jid,
        sender_phone: sender.split('@')[0],
        sender_name: msg._data?.notifyName || (chat && chat.name) || chatName || 'Unknown',
        is_group: isGroup,
        group_name: isGroup ? ((chat && chat.name) || chatName) : null,
        text: msg.body || '',
        has_media: !!fileInfo,
        media: fileInfo
    };

    // Forward to FastAPI Webhook
    try {
        const response = await axios.post(FASTAPI_WEBHOOK_URL, payload, { timeout: 30000 });
        console.log(`FastAPI webhook accepted message: ${payload.message_id}`);

        // If backend returned an automated reply, send it back
        if (response.data && response.data.reply_text) {
            await msg.reply(response.data.reply_text);
            console.log(`Sent auto-reply back to ${jid}`);
        }
    } catch (whErr) {
        console.error(`FastAPI webhook call failed: ${whErr.message}`);
    }
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

// GET Status
app.get('/status', (req, res) => {
    res.json({
        success: true,
        status: connectionStatus,
        connected: connectionStatus === 'connected',
        user: userInfo,
        has_qr: !!currentQRDataUrl,
        whitelist_count: whitelistJids.size
    });
});

// GET QR Code
app.get('/qr', (req, res) => {
    if (connectionStatus === 'connected') {
        return res.json({ success: true, connected: true, qr: null, qr_data_url: null });
    }
    if (!currentQRDataUrl) {
        return res.json({ success: false, connected: false, error: 'QR not ready yet' });
    }
    res.json({
        success: true,
        connected: false,
        qr: currentQR,
        qr_data_url: currentQRDataUrl
    });
});

// In-Memory Known Chats Cache
let knownChats = new Map();

// Helper to register or update a chat in cache
function registerChat(jid, name, isGroup) {
    if (!jid) return;
    if (jid.endsWith('@newsletter') || jid.endsWith('@broadcast') || jid.includes('status@broadcast')) return;
    const existing = knownChats.get(jid) || {};
    knownChats.set(jid, {
        id: jid,
        name: name || existing.name || (isGroup ? 'Group Chat' : jid.split('@')[0]),
        subject: name || existing.subject || (isGroup ? 'Group Chat' : jid.split('@')[0]),
        is_group: isGroup !== undefined ? isGroup : (jid.endsWith('@g.us') || existing.is_group || false),
        last_active: Date.now()
    });
}

// GET Chats / Groups
async function handleGetChats(req, res) {
    try {
        if (connectionStatus !== 'connected' || !client) {
            const cached = Array.from(knownChats.values()).filter(c => !c.id.endsWith('@newsletter') && !c.id.endsWith('@broadcast'));
            console.log(`getChats fallback to cached chats: ${cached.length}`);
            return res.json({ success: true, chats: cached, groups: cached, source: 'cache' });
        }
        let chats = [];
        try {
            // Read directly from WAWebCollections — avoids getChatModel() deserialization errors
            const rawChats = await Promise.race([
                client.pupPage.evaluate(() => {
                    try {
                        const chatCol = window.require('WAWebCollections').Chat;
                        if (!chatCol) return [];
                        return chatCol.getModelsArray().map(c => {
                            try {
                                return {
                                    id: c.id && c.id._serialized ? c.id._serialized : String(c.id || ''),
                                    name: c.name || c.formattedTitle || (c.id && c.id.user) || '',
                                    isGroup: !!c.isGroup,
                                    unreadCount: c.unreadCount || 0
                                };
                            } catch (e) { return null; }
                        }).filter(Boolean);
                    } catch (e) { return []; }
                }),
                new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 15000))
            ]);
            // Register into knownChats cache
            for (const chat of rawChats) {
                const id = chat.id;
                if (!id || id.endsWith('@newsletter') || id.endsWith('@broadcast') || id.includes('status@broadcast')) continue;
                registerChat(id, chat.name, chat.isGroup);
            }
            chats = rawChats;
        } catch (e) {
            const cached = Array.from(knownChats.values()).filter(c => !c.id.endsWith('@newsletter') && !c.id.endsWith('@broadcast'));
            console.log(`getChats fallback to cached chats: ${cached.length}`);
            return res.json({ success: true, chats: cached, groups: cached, source: 'cache' });
        }
        const filteredChats = chats.filter(c => {
            const id = c.id || '';
            return id && !id.endsWith('@newsletter') && !id.endsWith('@broadcast') && !id.includes('status@broadcast');
        });
        const result = filteredChats.map(c => ({
            id: c.id,
            name: c.name || c.id.split('@')[0],
            subject: c.name || c.id.split('@')[0],
            is_group: c.isGroup || false,
            unread_count: c.unreadCount || 0,
            last_message: null,
            is_monitored: whitelistJids.has(c.id)
        }));
        // Merge with known chats (e.g. ones seen via messages but not in store yet)
        knownChats.forEach((v, k) => {
            if (!k.endsWith('@newsletter') && !k.endsWith('@broadcast') && !result.find(r => r.id === k)) {
                result.push({ ...v, is_monitored: whitelistJids.has(k) });
            }
        });
        res.json({ success: true, chats: result, groups: result, source: 'live' });
    } catch (err) {
        const cached = Array.from(knownChats.values()).filter(c => !c.id.endsWith('@newsletter') && !c.id.endsWith('@broadcast'));
        res.json({ success: true, chats: cached, groups: cached, source: 'cache_error' });
    }
}

app.get('/chats', handleGetChats);
app.get('/groups', handleGetChats);

// DELETE Chat / Contact from bridge cache & whitelist
app.delete('/chats/:jid', (req, res) => {
    const jid = req.params.jid;
    if (jid) {
        knownChats.delete(jid);
        whitelistJids.delete(jid);
        console.log(`Removed chat from bridge: ${jid}`);
    }
    res.json({ success: true, message: `Removed ${jid}` });
});

// POST Send Message
app.post('/send', async (req, res) => {
    let { jid, text } = req.body || {};
    if (!jid || !text) {
        return res.status(400).json({ success: false, error: 'jid and text are required' });
    }
    if (connectionStatus !== 'connected' || !client) {
        return res.status(503).json({ success: false, error: 'WhatsApp not connected' });
    }
    // Normalize phone number to JID
    if (!jid.includes('@')) {
        const digits = jid.replace(/\D/g, '');
        jid = digits.length === 10 ? `91${digits}@s.whatsapp.net` : `${digits}@s.whatsapp.net`;
    }
    try {
        await client.sendMessage(jid, text);
        res.json({ success: true, message: 'Message sent', jid });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// POST Update Whitelist
app.post('/whitelist', (req, res) => {
    const { jids, monitored_groups } = req.body || {};
    whitelistJids.clear();
    if (Array.isArray(jids)) {
        jids.forEach(j => { if (j && !j.endsWith('@newsletter') && !j.endsWith('@broadcast')) whitelistJids.add(j); });
    }
    // Also populate known chats from provided monitored_groups
    if (Array.isArray(monitored_groups)) {
        monitored_groups.forEach(g => {
            if (g && g.id && !g.id.endsWith('@newsletter') && !g.id.endsWith('@broadcast')) {
                registerChat(g.id, g.subject || g.name, g.is_group || g.id.endsWith('@g.us'));
            }
        });
    }
    console.log(`Updated WhatsApp whitelist: ${whitelistJids.size} channels active.`);
    res.json({ success: true, whitelisted: whitelistJids.size });
});

// POST Reconnect / Restart Bridge
app.post('/reconnect', async (req, res) => {
    res.json({ success: true, message: 'Reconnect initiated' });
    isInitializing = false;
    setTimeout(() => initializeWhatsAppClient(), 500);
});

// POST Logout / Disconnect
app.post('/logout', async (req, res) => {
    try {
        if (client) {
            await client.logout();
        }
        res.json({ success: true, message: 'Logged out' });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// Start Express & Initialize WhatsApp
app.listen(PORT, '0.0.0.0', () => {
    console.log(`WhatsApp Bridge REST server running on http://0.0.0.0:${PORT}`);
    initializeWhatsAppClient();
});
