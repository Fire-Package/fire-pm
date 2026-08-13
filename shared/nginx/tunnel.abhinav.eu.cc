server {
    listen 80;
    listen [::]:80;
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name tunnel.abhinav.eu.cc "~^[a-f0-9]{8}-tunnel\.abhinav\.eu\.cc$";

    ssl_certificate /etc/ssl/abhinav.us.cc/fullchain.pem;
    ssl_certificate_key /etc/ssl/abhinav.us.cc/privkey.pem;

    access_log /var/log/nginx/tunnel.abhinav.eu.cc.access.log;
    error_log /var/log/nginx/tunnel.abhinav.eu.cc.error.log;

    error_page 500 = @invalid_tunnel;

    location / {
        if ($fire_tunnel_port = "") {
            return 500;
        }

        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        proxy_pass http://127.0.0.1:${fire_tunnel_port};
    }

    location @invalid_tunnel {
        default_type text/html;
        return 500 '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="3;url=https://abhinav.eu.cc" /></head><body style="font-family:sans-serif; text-align:center; margin-top:100px;"><h1>500 Not Allowed</h1><p>FUCK OFF DONT OPEN IT AGAIN</p></body></html>';
    }
}
