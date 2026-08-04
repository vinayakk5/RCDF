/**
 * 100% Free Self-Hosted WhatsApp Web Multi-Device Bridge for RCDF Operations
 * Powered by @whiskeysockets/baileys
 */
const crypto = require('crypto');
if (!globalThis.crypto) globalThis.crypto = crypto.webcrypto || crypto;
if (!global.crypto) global.crypto = crypto.webcrypto || crypto;

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
const AUTH_DIR = path.resolve(__dirname, 'auth_baileys_session');
const UPLOAD_DIR = path.resolve(__dirname, '../uploads/whatsapp');

if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

// Global State
let sock = null;
let currentQR = null;
let currentQRDataUrl = null;
let connectionStatus = 'disconnected';
let userInfo = null;
let whitelistJids = new Set();
let isInitializing = false;

// In-Memory Known Chats Cache
const knownChats = new Map();

function registerChat(jid, name, isGroup) {
    if (!jid || jid.endsWith('@newsletter') || jid.endsWith('@broadcast') || jid.includes('status@broadcast')) return;
    const existing = knownChats.get(jid) || {};
    knownChats.set(jid, {
        id: jid,
        name: name || existing.name || (isGroup ? 'Group Chat' : jid.split('@')[0]),
        subject: name || existing.subject || (isGroup ? 'Group Chat' : jid.split('@')[0]),
        is_group: isGroup !== undefined ? isGroup : (isJidGroup(jid) || existing.is_group || false),
        last_active: Date.now()
    });
}

console.log('--- Initializing RCDF WhatsApp Bridge (Baileys) ---');

async function initializeWhatsAppClient() {
    if (isInitializing) return;
    isInitializing = true;
    connectionStatus = 'connecting';
    currentQR = null;
    currentQRDataUrl = null;

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`Using WA v${version.join('.')}, isLatest: ${isLatest}`);

    sock = makeWASocket({
        logger: pino({ level: 'info' }),
        printQRInTerminal: false,
        version,
        auth: state,
        browser: Browsers.macOS('Desktop'),
        connectTimeoutMs: 60000,
        syncFullHistory: false
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
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
        }

        if (connection === 'open') {
            connectionStatus = 'connected';
            currentQR = null;
            currentQRDataUrl = null;
            userInfo = {
                id: sock.user.id.split(':')[0] + '@s.whatsapp.net',
                name: sock.user.name || 'RCDF Account',
                phone: sock.user.id.split(':')[0]
            };
            console.log(`WhatsApp Bridge Connected Live: ${userInfo.name} (${userInfo.phone})`);
        }

        if (connection === 'close') {
            const shouldReconnect = (lastDisconnect?.error)?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('Connection closed due to ', lastDisconnect?.error?.message || lastDisconnect?.error, ', reconnecting ', shouldReconnect);
            connectionStatus = 'disconnected';
            userInfo = null;
            isInitializing = false;
            
            if (shouldReconnect) {
                setTimeout(initializeWhatsAppClient, 5000);
            } else {
                console.log('Logged out. Please scan QR again.');
                if (fs.existsSync(AUTH_DIR)) fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                setTimeout(initializeWhatsAppClient, 5000);
            }
        }
    });

    sock.ev.on('contacts.upsert', (contacts) => {
        for (const contact of contacts) {
            registerChat(contact.id, contact.name || contact.notify || contact.verifiedName, isJidGroup(contact.id));
        }
    });

    sock.ev.on('messages.upsert', async (m) => {
        if (m.type !== 'notify') return;
        
        for (const msg of m.messages) {
            if (!msg.message || msg.key.fromMe) continue;

            const jid = msg.key.remoteJid;
            if (jid === 'status@broadcast') continue;

            const isGroup = isJidGroup(jid);
            const sender = isGroup ? msg.key.participant : jid;
            const pushName = msg.pushName || 'Unknown';

            registerChat(jid, pushName, isGroup);
            if (isGroup) registerChat(sender, pushName, false);

            if (whitelistJids.size > 0 && !whitelistJids.has(jid) && !whitelistJids.has(sender)) {
                console.log(`[Whitelist Skip] Ignored message from non-whitelisted sender: ${sender} / ${jid}`);
                continue;
            }

            const messageType = Object.keys(msg.message)[0];
            const messageContent = msg.message[messageType];
            
            let text = '';
            if (messageType === 'conversation') text = msg.message.conversation;
            else if (messageType === 'extendedTextMessage') text = msg.message.extendedTextMessage.text;
            else if (messageType === 'imageMessage') text = msg.message.imageMessage.caption || '';
            else if (messageType === 'documentMessage') text = msg.message.documentMessage.caption || '';

            console.log(`[Incoming Message] From: ${sender} | Chat: ${jid} | Type: ${messageType}`);

            let fileInfo = null;
            const hasMedia = ['imageMessage', 'videoMessage', 'documentMessage', 'audioMessage', 'stickerMessage'].includes(messageType);
            
            if (hasMedia) {
                try {
                    const buffer = await downloadMediaMessage(msg, 'buffer', {}, { logger: pino({ level: 'silent' }) });
                    if (buffer) {
                        const mime = messageContent.mimetype || 'application/octet-stream';
                        let ext = mime.split('/')[1]?.split(';')[0]?.toLowerCase() || 'bin';
                        if (ext === 'jpeg') ext = 'jpg';
                        const safeFilename = `wa_${Date.now()}_${msg.key.id.substring(0, 8)}.${ext}`;
                        const savePath = path.join(UPLOAD_DIR, safeFilename);

                        fs.writeFileSync(savePath, buffer);
                        fileInfo = {
                            filename: safeFilename,
                            path: savePath,
                            mimetype: mime,
                            filesize: buffer.length
                        };
                        console.log(`[Attachment Saved] ${savePath} (${mime}, size=${buffer.length})`);
                    }
                } catch (err) {
                    console.error(`[Attachment Failed] Could not download media for message ${msg.key.id}:`, err.message);
                }
            }

            const payload = {
                message_id: msg.key.id,
                timestamp: msg.messageTimestamp,
                from_jid: jid,
                sender_phone: sender.split('@')[0],
                sender_name: pushName,
                is_group: isGroup,
                group_name: isGroup ? (knownChats.get(jid)?.name || jid) : null,
                text: text,
                has_media: !!fileInfo,
                media: fileInfo
            };

            try {
                const response = await axios.post(FASTAPI_WEBHOOK_URL, payload, { timeout: 30000 });
                console.log(`FastAPI webhook accepted message: ${payload.message_id}`);

                if (response.data && response.data.reply_text) {
                    await sock.sendMessage(jid, { text: response.data.reply_text }, { quoted: msg });
                    console.log(`Sent auto-reply back to ${jid}`);
                }
            } catch (whErr) {
                console.error(`FastAPI webhook call failed: ${whErr.message}`);
            }
        }
    });

    isInitializing = false;
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

app.get('/chats', (req, res) => {
    const cached = Array.from(knownChats.values()).map(c => ({
        ...c,
        is_monitored: whitelistJids.has(c.id)
    }));
    res.json({ success: true, chats: cached, groups: cached, source: 'cache' });
});

app.get('/groups', (req, res) => {
    const cached = Array.from(knownChats.values()).map(c => ({
        ...c,
        is_monitored: whitelistJids.has(c.id)
    }));
    res.json({ success: true, chats: cached, groups: cached, source: 'cache' });
});

app.delete('/chats/:jid', (req, res) => {
    const jid = req.params.jid;
    if (jid) {
        knownChats.delete(jid);
        whitelistJids.delete(jid);
        console.log(`Removed chat from bridge: ${jid}`);
    }
    res.json({ success: true, message: `Removed ${jid}` });
});

app.post('/send', async (req, res) => {
    let { jid, text } = req.body || {};
    if (!jid || !text) return res.status(400).json({ success: false, error: 'jid and text are required' });
    if (connectionStatus !== 'connected' || !sock) return res.status(503).json({ success: false, error: 'WhatsApp not connected' });
    
    if (!jid.includes('@')) {
        const digits = jid.replace(/\D/g, '');
        jid = digits.length === 10 ? `91${digits}@s.whatsapp.net` : `${digits}@s.whatsapp.net`;
    }
    try {
        await sock.sendMessage(jid, { text });
        res.json({ success: true, message: 'Message sent', jid });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

app.post('/whitelist', (req, res) => {
    const { jids, monitored_groups } = req.body || {};
    whitelistJids.clear();
    if (Array.isArray(jids)) {
        jids.forEach(j => { if (j && !j.endsWith('@newsletter') && !j.endsWith('@broadcast')) whitelistJids.add(j); });
    }
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

app.post('/reconnect', async (req, res) => {
    res.json({ success: true, message: 'Reconnect initiated' });
    if (sock) sock.end();
    isInitializing = false;
    setTimeout(() => initializeWhatsAppClient(), 500);
});

app.post('/logout', async (req, res) => {
    try {
        if (sock) {
            await sock.logout();
        }
        res.json({ success: true, message: 'Logged out' });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`WhatsApp Bridge REST server running on http://0.0.0.0:${PORT}`);
    initializeWhatsAppClient();
});
