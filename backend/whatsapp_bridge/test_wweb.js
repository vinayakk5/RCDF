const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const path = require('path');

console.log('Initializing WhatsApp Web client...');

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: path.resolve(__dirname, 'auth_test_wweb') }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu'
        ]
    }
});

client.on('qr', async (qr) => {
    console.log('>>> GENUINE WHATSAPP QR GENERATED! <<<');
    console.log('QR Raw String Length:', qr.length);
    const dataUrl = await QRCode.toDataURL(qr);
    console.log('Data URL preview:', dataUrl.substring(0, 50) + '...');
    qrcodeTerminal.generate(qr, { small: true });
    process.exit(0);
});

client.on('ready', () => {
    console.log('Client is ready!');
});

client.on('auth_failure', (msg) => {
    console.error('Auth failure:', msg);
});

client.initialize().catch(err => {
    console.error('Initialization error:', err);
});
