import sys
import logging
from google_sheets import GoogleSheetsService

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        ws = s.sh_salary.worksheet('T8-2026')
        
        # Lấy rates từ Mapping
        rates = s.get_all_salary_rates()
        
        all_data = ws.get_all_values()
        
        updates = []
        for r in range(14, len(all_data)+1, 5):
            name = all_data[r-1][2].strip() if r-1 < len(all_data) and len(all_data[r-1]) > 2 else ""
            if not name:
                continue
                
            bot_nick = all_data[r-1][3].strip() if len(all_data[r-1]) > 3 else "" # Giả sử C là real name, D là nickname? Wait. 
            # In T8-2026, Name is C, but the Bot uses nickname to map. Let's find out the nickname from `bot_nick`?
            # Actually, the user's nickname is stored in column C sometimes? No, C is Bot Nickname.
            nick = name.lower()
            
            # rate = rates.get(nick, 16.0) # wait, rates keys are normalized?
            # get_all_salary_rates returns dictionary with normalized keys?
            # No, `get_all_salary_rates` keys are exactly what's in Mapping col B.
            # So let's match by normalizing.
            rate = 16.0
            for k, v in rates.items():
                if k.lower() == nick:
                    rate = v
                    break
            
            # Row r formulas:
            ap_formula = f"=AL{r}+AM{r}+AN{r}+AJ{r}"
            as_formula = f"=AP{r}*{rate:g}"
            updates.append({'range': f'AP{r}', 'values': [[ap_formula]]})
            updates.append({'range': f'AS{r}', 'values': [[as_formula]]})
            
            # Row r+1 formula:
            at_formula = f"=SUM(AS{r}-AQ{r+1}+AR{r+1})"
            updates.append({'range': f'AT{r+1}', 'values': [[at_formula]]})
            
            print(f"Updated formulas for {name} at row {r} with rate {rate:g}k")
        
        if updates:
            ws.batch_update(updates, value_input_option='USER_ENTERED')
            print("Đã tự động cập nhật công thức tính lương mới thành công!")
        else:
            print("Không tìm thấy nhân viên nào cần cập nhật.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
