# UI/UX & Theme — Màn Hình Đăng Nhập

---

## 1. Layout

Màn hình chia 2 cột nằm ngang trên desktop, xếp dọc trên mobile.

```
┌─────────────────────────────────────────────────────┐
│                   Background layer                  │
│                                                     │
│   ┌──────────────────┐     ┌─────────────────────┐  │
│   │   Cột trái       │     │   Cột phải          │  │
│   │   Brand / Copy   │     │   Login Card        │  │
│   └──────────────────┘     └─────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

| Thuộc tính | Giá trị |
|---|---|
| Container max-width | `max-w-6xl` |
| Gap giữa 2 cột | `gap-12` |
| Padding ngoài | `p-8` |
| Responsive | `flex-col` (mobile) → `lg:flex-row` (desktop) |

---

## 2. Background — 3 lớp chồng nhau

### Lớp 1 — Màu nền
```
#F8FAFC
```

### Lớp 2 — Aurora Blobs (3 quả cầu gradient mờ)

| Vị trí | Màu | Kích thước | Blur | Animation |
|---|---|---|---|---|
| Trên trái | `rgba(16,207,201, 0.3)` turquoise | 70% × 70% | 100px | pulse 8s infinite |
| Dưới phải | `rgba(22,49,94, 0.2)` navy | 80% × 80% | 120px | pulse 12s alternate |
| Giữa phải | `rgba(16,207,201, 0.2)` turquoise nhạt | 50% × 50% | 80px | pulse 10s alternate-reverse |

Cả 3 dùng `radial-gradient(circle, màu 0%, transparent 70%)` và `border-radius: 50%`.

### Lớp 3 — Particle Network
Canvas vẽ các điểm nhỏ nối với nhau bằng đường thẳng, màu navy `rgba(22,49,94, opacity)`, khoảng 80 hạt, chuyển động chậm.

---

## 3. Cột Trái — Brand

### Logo block
- Nền trắng, bo góc 4px, border `rgba(22,49,94, 0.1)`, shadow nhẹ
- Kích thước: `w-48 h-20`

### Tên thương hiệu
```
COTECCO[N]S
```
- Font: **Space Grotesk**, 42px, bold, tracking `-2px`
- Chữ `N` màu turquoise `#10CFC9`, các chữ còn lại navy `#16315E`

### Tagline dưới tên
```
BUILDING FUTURES
```
- Font: monospace (JetBrains Mono), 14px, tracking `3px`, uppercase
- Màu: `#10CFC9`

### Tiêu đề chính
```
QUẢN LÝ
  TÀI SẢN
```
- "QUẢN LÝ": 42px, black weight, tracking `-3.5px`, navy
- "TÀI SẢN": 54px, black weight, tracking `-4px`, in nghiêng (`italic`), thụt vào `ml-16`
- Màu "TÀI SẢN": gradient `from-[#10CFC9] to-[#16315E]`, `bg-clip-text`, `mix-blend-multiply`

### Dòng dưới cùng
```
CORPORATE PRECISION • SWISS MINIMALISM • RFID ENABLED
```
- Font: monospace, 10px, tracking `1px`, màu `rgba(22,49,94, 0.7)`

### Animation
4 phần tử slide-up lần lượt với delay tăng dần (100ms → 300ms → 500ms → 700ms).

---

## 4. Cột Phải — Login Card

### Card container
```css
background: rgba(255, 255, 255, 0.7)
backdrop-filter: blur(24px)
border-radius: 16px   /* rounded-2xl */
padding: 48px         /* p-12 */
min-height: 420px
box-shadow: 0 8px 32px rgba(22,49,94,0.08)
```

Viền animated: dùng `@property --angle` xoay gradient từ turquoise sang navy quanh border.

### Tiêu đề card
```
ĐĂNG NHẬP
```
- Font: Space Grotesk, 30px, semibold, tracking `-1px`, navy

### Input — Floating Label

Mỗi input có pattern label bay lên khi focus hoặc có giá trị:

```
Trạng thái bình thường:
┌─────────────────────┐
│ EMAIL               │   ← label ở giữa, 12px
│                     │
└─────────────────────┘

Khi focus / có giá trị:
┌─────────────────────┐
│ EMAIL               │   ← label nhỏ lại (9.6px), bay lên top
│ user@example.com    │
└─────────────────────┘
```

**CSS quan trọng:**
- Input padding: `1.25rem 1rem 0.5rem` (tạo chỗ cho label bay lên)
- Input nền: `rgba(255,255,255, 0.6)` → `#fff` khi focus
- Focus ring: `box-shadow: 0 0 0 4px rgba(16,207,201, 0.15)`
- Focus border: `#10CFC9`
- Label transition: `all 0.2s cubic-bezier(0.4,0,0.2,1)`
- **Bắt buộc:** `placeholder=" "` (1 dấu cách) để selector `:not(:placeholder-shown)` hoạt động

### Nút Submit

```
ĐĂNG NHẬP HỆ THỐNG
```

| State | Style |
|---|---|
| Bình thường | nền `#10CFC9`, chữ `#111b21`, shadow `0 4px 14px rgba(16,207,201,0.25)` |
| Hover | shadow lớn hơn, nhấc lên `-translate-y-0.5` |
| Loading | text đổi thành "ĐANG XÁC THỰC...", `opacity: 0.7` |

- Font: semibold, 16px
- Border radius: `rounded-xl` (12px)
- Padding: `py-4` (16px trên dưới), full width

---

## 5. Color Palette

| Tên | Hex | Dùng cho |
|---|---|---|
| Biscay Navy | `#16315E` | Tiêu đề, text chính, nền sidebar |
| Navy Dark | `#0f2549` | Hover state |
| Bright Turquoise | `#10CFC9` | Accent, nút CTA, focus, active |
| Turquoise Dark | `#0EA5A0` | Hover accent |
| Off-White | `#F8FAFC` | Nền trang |
| Pure White | `#FFFFFF` | Card, input |
| Slate 500 | `#64748B` | Text mờ, placeholder |
| Border | `#E2E8F0` | Viền input |

---

## 6. Typography

| Font | Dùng cho | Class |
|---|---|---|
| **Space Grotesk** | Tiêu đề lớn, tên thương hiệu | `.display`, `h1`, `h2` |
| **IBM Plex Sans** | Body text mặc định | `font-sans` |
| **JetBrains Mono** | Tagline, mã, số | `.mono` |
| **Inter Tight** | Nút bấm, UI labels | `.tight` |

Import từ Google Fonts (tất cả weight 400–700).

---

## 7. Animations

### Slide-up (entrance)
```css
@keyframes slide-up {
  from { opacity: 0; transform: translateY(24px); }
  to   { opacity: 1; transform: translateY(0); }
}
duration: 0.8s
easing: cubic-bezier(0.16, 1, 0.3, 1)   /* spring */
```

Delay theo thứ tự xuất hiện:
- Logo block: `0.1s`
- Tiêu đề QUẢN LÝ TÀI SẢN: `0.3s`
- Tagline dưới: `0.5s`
- Login card: `0.7s`

### Pulse (aurora blobs)
Tailwind `animate-[pulse_Xs_ease-in-out_infinite]` với duration khác nhau cho mỗi blob để tạo cảm giác tự nhiên.

### Floating label
`transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1)`

### Nút hover
`transition-all` với `hover:-translate-y-0.5` và shadow tăng dần.

---

## 8. Responsive

| Breakpoint | Layout |
|---|---|
| Mobile (`< lg`) | Cột trái ở trên, card ở dưới, flex-col |
| Desktop (`≥ lg`) | Hai cột nằm ngang, flex-row, brand trái / card phải |

Card luôn `max-w-md` (448px) và `w-full`.
