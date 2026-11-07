# Runbook: deploy YouTube Bulk Uploader bằng AI agent điều khiển trình duyệt

Tài liệu này hướng dẫn một AI agent deploy tool theo `README.md`. Agent dùng gcloud CLI cho các lệnh. Agent điều khiển trình duyệt của người dùng qua CDP (Chrome DevTools Protocol) cho các trang Google Cloud Console.
Các bước đã chạy thật trên Linux với một trình duyệt nhân Chromium. Áp dụng được cho Chrome, Brave, Edge và Chromium.

## Biến dùng trong tài liệu

Thay các biến sau bằng giá trị thật trước khi chạy lệnh.

| Biến | Ý nghĩa |
|------|---------|
| `<ACCOUNT>` | Tài khoản Google sở hữu GCP project, thư mục Drive nguồn và kênh YouTube đích |
| `<PROJECT_ID>` | ID của GCP project |
| `<FOLDER_ID>` | ID thư mục Drive chứa video |
| `<SECRETS_DIR>` | Thư mục local chứa secret, ngoài repo, ví dụ `~/.config/ytbu` |
| `<PROFILE_DIR>` | Thư mục profile của trình duyệt (xem bước 1) |

## Việc phải hỏi người dùng trước khi bắt đầu

Agent không tự quyết các việc sau:

1. Dùng tài khoản Google nào (`<ACCOUNT>`). Trình duyệt có thể đăng nhập nhiều tài khoản.
2. Dùng project có sẵn hay tạo project mới.
3. Dùng thư mục Drive có sẵn hay tạo thư mục mới.
4. Hành động sau khi upload: `rename` (mặc định), `move` hoặc `delete`.
5. Chạy lệnh ở máy local (cần cài gcloud) hay trong Cloud Shell.

## Thứ tự các bước

| # | Bước | Cần billing |
|---|------|------------|
| 1 | Kết nối agent vào trình duyệt qua CDP | Không |
| 2 | Cài gcloud CLI, đăng nhập | Không |
| 3 | Chọn project, kiểm tra billing | Không |
| 4 | Bật API Drive, YouTube, Sheets | Không |
| 5 | Cấu hình OAuth consent screen | Không |
| 6 | Tạo OAuth client loại Desktop | Không |
| 7 | Lấy refresh token | Không |
| 8 | Chọn hoặc tạo thư mục Drive, ghi ID vào `settings.ini` | Không |
| 9 | Bật billing | Người dùng tự làm |
| 10 | `./setup.sh enable_apis` | Có |
| 11 | Tạo 3 secret trong Secret Manager | Có |
| 12 | `./setup.sh deploy_all` | Có |
| 13 | `./test_function.sh` | Có |

Nếu billing chưa bật, làm bước 1 đến 8, rồi dừng và báo người dùng.

## Bước 1: kết nối agent vào trình duyệt

Người dùng bật remote debugging trong trình duyệt đang chạy. Mở trang `chrome://inspect/#remote-debugging` (Brave: `brave://inspect/#remote-debugging`, Edge: `edge://inspect/#remote-debugging`), tích "Allow remote debugging for this browser instance".

Trình duyệt ghi cổng (dòng 1) và đường dẫn WebSocket (dòng 2) vào file `<PROFILE_DIR>/DevToolsActivePort`. Vị trí `<PROFILE_DIR>` trên Linux:

| Trình duyệt | `<PROFILE_DIR>` |
|-------------|-----------------|
| Chrome | `~/.config/google-chrome` |
| Chromium | `~/.config/chromium` |
| Brave | `~/.config/BraveSoftware/Brave-Browser` |
| Edge | `~/.config/microsoft-edge` |

Trên macOS, profile nằm trong `~/Library/Application Support/<tên trình duyệt>`.

Ở chế độ này, `http://127.0.0.1:<port>/json/version` trả về 404. Vì vậy agent phải kết nối bằng URL WebSocket, không dùng URL HTTP.
Wrapper `bu.sh` cho skill `browser-use`:

```bash
#!/bin/bash
F=<PROFILE_DIR>/DevToolsActivePort
BU_CDP_WS=ws://127.0.0.1:$(sed -n 1p $F)$(sed -n 2p $F) exec timeout ${T:-120} browser-use
```

Hộp thoại "Allow remote debugging?" chỉ được hỏi người dùng một lần trong cả phiên làm việc. Trình duyệt hiện hộp thoại này mỗi khi có một kết nối WebSocket mới.
Skill `browser-use` chạy một daemon nền giữ một kết nối duy nhất. Các lệnh `bu.sh` sau đó dùng lại kết nối này qua IPC, nên không tạo hộp thoại mới.

Quy tắc:

1. Trước lệnh `bu.sh` đầu tiên, báo người dùng: "Trình duyệt sắp hiện hộp thoại Allow remote debugging. Bấm Allow một lần."
2. Chạy lệnh đầu tiên với thời gian chờ dài, ví dụ `T=300 bu.sh`, để người dùng có đủ thời gian bấm. Chỉ chạy một lần.
3. Nếu lệnh đầu thất bại, không chạy lại. Hỏi người dùng đã bấm Allow chưa, rồi mới chạy lại.
4. Sau khi kết nối thành công, không làm gì tạo kết nối mới: không kill hoặc restart daemon, không gọi `restart_daemon()`, không đổi `BU_NAME`, không chạy song song nhiều agent với daemon khác nhau.
5. Mọi lệnh sau dùng cùng một `bu.sh` và cùng `BU_NAME`. Nếu trình duyệt bị đóng rồi mở lại, đường dẫn WebSocket đổi và phải hỏi Allow lại. Báo người dùng lý do trước khi hỏi.

Helper `h.py`. Chạy `exec(open("h.py").read())` ở đầu mỗi lệnh `bu.sh`:

```python
import time, base64
cdp("Page.bringToFront")   # bắt buộc: tab nền không nhận click
def ax_click(name, role=None, exact=False, idx=0):
    nodes=cdp("Accessibility.getFullAXTree")["nodes"]; hits=[]
    for n in nodes:
        nm=(n.get("name") or {}).get("value","") or ""
        r=(n.get("role") or {}).get("value","")
        if (nm==name if exact else name in nm) and (role is None or r==role) and n.get("backendDOMNodeId"):
            hits.append((nm,r,n["backendDOMNodeId"]))
    if len(hits)<=idx: print("NOT FOUND",name,role); return False
    nm,r,b=hits[idx]
    try: cdp("DOM.scrollIntoViewIfNeeded",backendNodeId=b)
    except Exception: pass
    q=cdp("DOM.getBoxModel",backendNodeId=b)["model"]["content"]
    click_at_xy(sum(q[0::2])/4,sum(q[1::2])/4); print("clicked",repr(nm),r); return True
def txt(n=1500): print(js(f"(document.querySelector('main')||document.body).innerText.slice(0,{n})"))
def shot(p="s.png"): open(p,"wb").write(base64.b64decode(cdp("Page.captureScreenshot",format="png")["data"]))
def typ(s): cdp("Input.insertText",text=s)
def chip_email(email):   # ô nhập email dạng chip
    ax_click("Text field for emails", role="textbox"); typ(email)
    cdp("Input.dispatchKeyEvent",type="keyDown",key=",",code="Comma",text=",",windowsVirtualKeyCode=188)
    cdp("Input.dispatchKeyEvent",type="keyUp",key=",",code="Comma",windowsVirtualKeyCode=188)
    time.sleep(1)
    print("chips:", js("[...document.querySelectorAll('mat-chip-row')].map(r=>r.textContent.trim()).join('|')"))
def pick_account(email):   # trang chọn tài khoản Google
    r=js(f"""(()=>{{const e=document.querySelector('[data-identifier="{email}"]');if(!e)return null;const b=e.getBoundingClientRect();return [b.x+b.width/2,b.y+b.height/2]}})()""")
    if r: click_at_xy(*r)
    return r
```

Lưu ý khi điều khiển Google Cloud Console:

- Nếu trình duyệt đăng nhập nhiều tài khoản Google, thêm `&authuser=<ACCOUNT>` vào mọi URL console. Nếu không, console mở bằng tài khoản mặc định.
- Gọi `Page.bringToFront` trước khi click. Click vào tab nền không có tác dụng.
- Ô email dạng chip (Contact email, Test users) không tạo chip khi dấu phẩy đi qua `Input.insertText`. Dùng `chip_email()`, hàm này gửi phím `,` thật.
- Không bấm Enter trong ô email chip. Enter chọn gợi ý autocomplete và có thể thêm nhầm email khác. Nếu thêm nhầm, tìm `mat-chip-row` chứa email đó và click nút remove bên trong bằng JS.
- Làm từng bước và kiểm tra trang sau mỗi bước. Nếu một `ax_click` trả về NOT FOUND, các click sau có thể rơi vào trang sai.
- Nút "Save" trong drawer có thể trùng tên với nút khác. Nếu `ax_click("Save")` không có tác dụng, click nút "Save" cuối cùng đang hiển thị, hoặc chụp màn hình rồi click theo tọa độ. Tọa độ CSS bằng tọa độ screenshot chia cho device pixel ratio.

## Bước 2: cài gcloud và đăng nhập

Nếu máy chưa có gcloud, cài bản tarball vào thư mục home (không cần sudo):

```bash
curl -sSLo /tmp/gcsdk.tgz https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz
tar -xzf /tmp/gcsdk.tgz -C ~
~/google-cloud-sdk/install.sh --quiet --usage-reporting=false --path-update=false
export PATH=~/google-cloud-sdk/bin:$PATH   # cần cho mọi lệnh setup.sh
```

Đăng nhập mà không để gcloud tự mở trình duyệt, rồi mở URL bằng agent:

```bash
BROWSER=/bin/true gcloud auth login > gauth.log 2>&1 &   # chạy nền
grep -o 'https://accounts.google.com[^ ]*' gauth.log      # URL để goto_url
```

Trong trình duyệt: `pick_account("<ACCOUNT>")`, rồi bấm "Continue" nếu Google hỏi. Trang `.../sdk/auth_success` nghĩa là đăng nhập xong. Kiểm tra bằng `gcloud auth list`.

## Bước 3 và 4: chọn project, bật API miễn phí

```bash
gcloud projects list
gcloud config set project <PROJECT_ID>
gcloud billing accounts list                     # cột OPEN phải là True
gcloud billing projects describe <PROJECT_ID>    # billingEnabled
gcloud services enable drive.googleapis.com youtube.googleapis.com sheets.googleapis.com
```

## Bước 5: OAuth consent screen

1. Mở `https://console.cloud.google.com/auth/overview?project=<PROJECT_ID>&authuser=<ACCOUNT>`, bấm "Get started".
2. App name: `YouTube Bulk Uploader`. User support email: `<ACCOUNT>`. Bấm Next.
3. Audience: chọn External. Bấm Next.
4. Contact Information: `chip_email("<ACCOUNT>")`. Bấm Next.
5. Tích ô "I agree to the Google API Services: User Data Policy", bấm Continue, rồi Create.
6. Mở `https://console.cloud.google.com/auth/audience?project=<PROJECT_ID>&authuser=<ACCOUNT>`, bấm "Add users", `chip_email("<ACCOUNT>")`, bấm Save. Kiểm tra dòng "1 user (1 test, 0 other)".

App mới tạo ở trạng thái Testing. Ở trạng thái này, refresh token hết hạn sau 7 ngày, và Function chạy theo lịch sẽ lỗi xác thực.
Muốn bấm "Publish app", phải điền homepage URL và privacy policy URL ở trang Branding trước. Sau khi publish, lấy lại refresh token (bước 7) và cập nhật secret `ytbu-refresh-token`. Hỏi người dùng các URL này, agent không tự bịa.

## Bước 6: OAuth client Desktop

1. Mở `https://console.cloud.google.com/auth/clients/create?project=<PROJECT_ID>&authuser=<ACCOUNT>`.
2. Application type: Desktop app. Name: `YouTube Uploader Client`. Bấm Create.
3. Hộp thoại hiện Client ID và Client secret một lần duy nhất. Đọc hai giá trị bằng regex và ghi thẳng vào file trong cùng script. Không in `innerText` của hộp thoại ra log.
4. Bấm OK.

Script mẫu (chạy trong `bu.sh`):

```python
import json, os, re
t=js("document.body.innerText")
cid=re.search(r"Client ID\s+(\S+\.apps\.googleusercontent\.com)",t).group(1)
sec=re.search(r"Client secret\s+(GOCSPX-\S+)",t).group(1)
os.umask(0o077)
json.dump({"installed":{"client_id":cid,"client_secret":sec,"project_id":"<PROJECT_ID>",
  "auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token",
  "redirect_uris":["http://localhost"]}}, open(os.path.expanduser("<SECRETS_DIR>/client_secret.json"),"w"))
```

## Bước 7: refresh token

```bash
python3 -m venv /tmp/venv && /tmp/venv/bin/pip -q install google-auth-oauthlib google-api-python-client
BROWSER=/bin/true /tmp/venv/bin/python -u get_refresh_token.py <SECRETS_DIR>/client_secret.json > rt.log 2>&1 &
grep -o 'https://accounts.google.com[^ ]*' rt.log   # mở URL này trong trình duyệt
```

Trong trình duyệt:

1. `pick_account("<ACCOUNT>")`.
2. Trang cảnh báo app chưa được Google xác minh: bấm "Continue". Đây là app của chính người dùng.
3. Trang cấp quyền: tích "Select all", bấm "Continue". Trình duyệt chuyển về `http://localhost:<port>/` và báo hoàn tất.

Nếu giao diện Google hiện tiếng Việt, tên nút là "Tiếp tục" và "Chọn tất cả".

Lưu token mà không in ra, rồi xóa log:

```bash
umask 077
grep -o 'ytbu-refresh-token --value "[^"]*"' rt.log | sed 's/.*--value "//;s/"$//' > <SECRETS_DIR>/refresh_token
rm rt.log
```

## Bước 8: thư mục Drive

Kiểm tra token bằng cách gọi API thật. Script dưới đây tạo thư mục "YouTube Uploads" nếu chưa có, và in kênh YouTube đích:

```python
import json, os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
d=os.path.expanduser("<SECRETS_DIR>/")
c=json.load(open(d+"client_secret.json"))["installed"]
cr=Credentials(None, refresh_token=open(d+"refresh_token").read().strip(),
               client_id=c["client_id"], client_secret=c["client_secret"], token_uri=c["token_uri"])
drive=build("drive","v3",credentials=cr)
q="name='YouTube Uploads' and mimeType='application/vnd.google-apps.folder' and trashed=false"
ex=drive.files().list(q=q,fields="files(id)").execute()["files"]
f=ex[0] if ex else drive.files().create(body={"name":"YouTube Uploads","mimeType":"application/vnd.google-apps.folder"},fields="id").execute()
print("folder", f["id"])
yt=build("youtube","v3",credentials=cr)
print("channels", [(i["id"], i["snippet"]["title"]) for i in yt.channels().list(part="snippet",mine=True).execute().get("items",[])])
```

Ghi ID vào `settings.ini`:

```ini
[arguments]
drive-root-folder-id = <FOLDER_ID>
```

Để trống `youtube-channel-id` thì Function upload lên kênh mặc định của `<ACCOUNT>`.

## Bước 9: billing

Agent không nhập thông tin thanh toán. Nếu `gcloud billing accounts list` trả về rỗng hoặc `OPEN=False`, dừng và báo người dùng:

- Không có billing account: người dùng tạo tại `https://console.cloud.google.com/billing?authuser=<ACCOUNT>`.
- Billing account đóng, console hiện "Your free trial requires a prepayment": người dùng bấm "Make a payment" để mở lại.

Sau đó người dùng liên kết billing account với `<PROJECT_ID>`. Kiểm tra: `gcloud billing projects describe <PROJECT_ID>` trả về `billingEnabled: true`.

## Bước 10 đến 13: deploy

1. Bật các API còn lại:

   ```bash
   export PATH=~/google-cloud-sdk/bin:$PATH
   ./setup.sh enable_apis
   ```

2. Tạo secret, đọc giá trị từ file và không in ra:

   ```bash
   ./setup.sh create_secret --secret ytbu-client-id --value "$(jq -r .installed.client_id <SECRETS_DIR>/client_secret.json)"
   ./setup.sh create_secret --secret ytbu-client-secret --value "$(jq -r .installed.client_secret <SECRETS_DIR>/client_secret.json)"
   ./setup.sh create_secret --secret ytbu-refresh-token --value "$(cat <SECRETS_DIR>/refresh_token)"
   ```

3. Deploy Function và Scheduler job. Lịch nằm ở `settings.ini` mục `scheduler.schedule`:

   ```bash
   ./setup.sh deploy_all
   ```

4. Chép một video thử vào thư mục Drive `<FOLDER_ID>`, rồi chạy:

   ```bash
   ./test_function.sh
   ```

   Thành công khi video xuất hiện trên kênh YouTube và file trong Drive đổi tên thành video ID (với action `rename`). Xem log ở Cloud Console, mục Cloud Run functions, `youtube-bulk-uploader`.

## Quy tắc an toàn

- Không commit, không in client secret và refresh token ra log hoặc chat. Lưu trong `<SECRETS_DIR>` với quyền 600.
- Không nhập thông tin thanh toán, mật khẩu hoặc mã MFA. Dừng và hỏi người dùng.
- Nếu đổi tài khoản giữa chừng, chuyển file secret cũ sang thư mục con thay vì xóa. Báo người dùng tài nguyên nào còn lại ở project cũ.

## Lỗi đã gặp

| Lỗi | Nguyên nhân | Cách xử lý |
|-----|------------|-----------|
| `BU_CDP_URL ... HTTP Error 404` | Remote debugging bật qua trang inspect không có endpoint `/json/version` | Dùng `BU_CDP_WS` lấy từ `DevToolsActivePort` |
| `CDP WS handshake failed: timed out` | Người dùng chưa bấm Allow trong thời gian chờ | Không chạy lại ngay. Hỏi người dùng, rồi chạy lại một lần với `T=300` |
| Người dùng bị hỏi Allow nhiều lần | Agent tạo kết nối mới: restart daemon, đổi `BU_NAME`, hoặc chạy lại lệnh đầu nhiều lần | Giữ một daemon cho cả phiên, xem quy tắc ở bước 1 |
| Click không có tác dụng | Tab đang ở nền | `cdp("Page.bringToFront")` |
| `gzip: stdin: not in gzip format` khi cài gcloud | URL tarball thiếu `/downloads/`, trả về trang 404 | Dùng URL ở bước 2 |
| Console mở bằng tài khoản khác | Trình duyệt đăng nhập nhiều tài khoản | Thêm `&authuser=<ACCOUNT>` vào URL |
| Thêm nhầm email trong ô chip | Enter chọn gợi ý autocomplete | Dùng `chip_email()`, xóa chip nhầm bằng nút remove |
| Không bấm được "Publish app" | Thiếu homepage URL và privacy policy URL | Hỏi người dùng URL, hoặc chấp nhận Testing (token 7 ngày) |
