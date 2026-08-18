import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import math

st.set_page_config(page_title="Dong A Logistics Optimizer", layout="wide")

st.title("🚛 Hệ thống Tối ưu Tuyến đường & Kiểm soát Chi phí")
st.caption("Công nghệ: Google OR-Tools AI | Tối ưu bằng Tiền thật (VNĐ) & Giới hạn Quãng đường")

# --- HÀM TÍNH KHOẢNG CÁCH ---
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def create_distance_matrix(df):
    num_nodes = len(df)
    matrix = []
    for i in range(num_nodes):
        row = []
        for j in range(num_nodes):
            if i == j:
                row.append(0)
            else:
                dist = haversine_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
                row.append(int(dist * 1000)) # Lưu khoảng cách thuần bằng mét
        matrix.append(row)
    return matrix

# --- BẢNG ĐIỀU KHIỂN BÊN TRÁI ---
st.sidebar.header("⚙️ 1. Cấu hình Đội xe")

if "fleet_size" not in st.session_state:
    st.session_state.fleet_size = 6

num_vehicles = st.sidebar.number_input("Số lượng xe điều phối:", min_value=1, step=1, value=st.session_state.fleet_size)

if "vehicle_df" not in st.session_state or st.session_state.fleet_size != num_vehicles:
    st.session_state.fleet_size = num_vehicles
    st.session_state.vehicle_df = pd.DataFrame({
        "STT": [i + 1 for i in range(num_vehicles)],  # Đánh số bắt đầu từ 1
        "Biển số xe": [f"51C-{12340 + i}" for i in range(num_vehicles)],
        "Tải trọng (Tấn)": [30] * num_vehicles
    })

edited_vehicles = st.sidebar.data_editor(
    st.session_state.vehicle_df, 
    use_container_width=True, 
    hide_index=True,  # Ẩn cột index số 0 mặc định
    disabled=["STT"]  # Khóa cột STT để người dùng không gõ nhầm
)
st.session_state.vehicle_df = edited_vehicles

vehicle_names = edited_vehicles["Biển số xe"].astype(str).tolist()
vehicle_capacities = edited_vehicles["Tải trọng (Tấn)"].astype(int).tolist()
has_duplicate_vehicles = len(vehicle_names) != len(set(vehicle_names))
if has_duplicate_vehicles:
    st.sidebar.error("⚠️ LỖI: Biển số xe đang bị trùng lặp! Vui lòng sửa lại.")

st.sidebar.markdown("---")
st.sidebar.header("💰 2. Cấu hình Chi phí (VNĐ)")

with st.sidebar.expander("⛽ Chi tiết Biến phí nhiên liệu", expanded=True):
    fuel_consumption = st.number_input(
        "Định mức tiêu hao (Lít/100km):", 
        min_value=1.0, 
        value=30.0, 
        step=1.0, 
        format="%.1f"
    )
    fuel_price = st.number_input(
        "Đơn giá nhiên liệu (VNĐ/Lít):", 
        min_value=1000, 
        value=20000, 
        step=500
    )
    st.caption(f"💵 Giá dầu: **{fuel_price:,.0f} VNĐ/Lít**")

# Tự động tính Biến phí nhiên liệu trên 1 km theo công thức
fuel_cost_per_km = (fuel_consumption / 100.0) * fuel_price

st.sidebar.markdown(f"**Biến phí nhiên liệu:** `{fuel_cost_per_km:,.0f} VNĐ/km`")
st.sidebar.caption(f"*({fuel_consumption} Lít ÷ 100) × {fuel_price:,.0f} đ*")

with st.sidebar.expander("🛠️ Chi tiết cấu thành Định phí (Tháng)", expanded=False):
    cost_depreciation = st.number_input("Khấu hao xe (VNĐ/tháng):", min_value=0, value=12000000, step=1000000)
    cost_salary = st.number_input("Lương cố định tài xế/lơ xe (VNĐ/tháng):", min_value=0, value=10000000, step=500000)
    cost_parking = st.number_input("Phí bến bãi, xuất/nhập bến (VNĐ/tháng):", min_value=0, value=3000000, step=200000)
    cost_toll = st.number_input("Phí cầu đường cố định (VNĐ/tháng):", min_value=0, value=2000000, step=200000)
    cost_insurance = st.number_input("Bảo hiểm, đăng kiểm (VNĐ/tháng):", min_value=0, value=1500000, step=100000)
    cost_admin = st.number_input("Chi phí quản lý, điều vận (VNĐ/tháng):", min_value=0, value=1500000, step=100000)
    
    monthly_trips = st.number_input("Số chuyến xe dự kiến / tháng:", min_value=1, value=60, step=5)

# Tự động tính tổng định phí tháng và phân bổ cho 1 chuyến
total_fixed_cost_month = (cost_depreciation + cost_salary + cost_parking + 
                          cost_toll + cost_insurance + cost_admin)

fixed_vehicle_cost = int(total_fixed_cost_month / monthly_trips) if monthly_trips > 0 else 0

st.sidebar.markdown(f"**Định phí xuất xe:** `{fixed_vehicle_cost:,.0f} VNĐ/chuyến`")
st.sidebar.caption(f"*(Tổng định phí: {total_fixed_cost_month:,.0f} đ/tháng ÷ {monthly_trips} chuyến)*")

max_acceptable_cost = st.sidebar.number_input("Mức tối đa chi phí chấp nhận:", min_value=0, value=3000000, step=100000)
st.sidebar.caption(f"💵 Đang nhập: **{max_acceptable_cost:,.0f} VNĐ**")
st.sidebar.markdown("---")
st.sidebar.header("📏 3. Giới hạn Ghép chiều về")

st.sidebar.info("💡 **Logic:** Chỉ ghép chiều về nếu chi phí phát sinh do đi vòng (Detour) nhỏ hơn chi phí chạy rỗng (Empty-leg) tiết kiệm được.")

with st.sidebar.expander("⚖️ Phân tích Hòa vốn (Break-even)", expanded=True):
    # 1. Tự động tính Quãng đường rỗng trung bình (Depot -> Delivery)
    avg_empty_km = 40.0  # Mặc định dự phòng an toàn
    
    if 'df' in locals() and not df.empty:
        # Nhận diện tên cột (Type hoặc Loại điểm)
        col_type = 'Type' if 'Type' in df.columns else 'Loại điểm'
        col_lat = 'Vĩ độ' if 'Vĩ độ' in df.columns else 'Lat'
        col_lon = 'Kinh độ' if 'Kinh độ' in df.columns else 'Lng'
        
        depots = df[df[col_type] == 'Depot']
        deliveries = df[df[col_type] == 'Delivery']
        
        if not depots.empty and not deliveries.empty:
            depot_row = depots.iloc[0]
            total_dist = 0
            
            for _, row in deliveries.iterrows():
                lat1, lon1 = depot_row[col_lat], depot_row[col_lon]
                lat2, lon2 = row[col_lat], row[col_lon]
                
                # Công thức Haversine tính khoảng cách GPS (Đường chim bay)
                R = 6371.0 # Bán kính trái đất (km)
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                dist_km = R * c
                
                # Nhân thêm hệ số ngoằn ngoèo thực tế (Detour Index = 1.3)
                total_dist += (dist_km * 1.3)
                
            # Chia trung bình
            avg_empty_km = total_dist / len(deliveries)
            
    st.text_input(
        "Quãng đường rỗng trung bình (km):",
        value=f"{avg_empty_km:.1f} km",
        disabled=True,
        help="Hệ thống tự động tính: Khoảng cách từ Depot đến các điểm Delivery, đã nhân hệ số đường bộ (1.3) để sát thực tế."
    )
    
    # 2. Chi phí chạy rỗng tránh được (Hệ thống tự tính)
    saved_cost = avg_empty_km * fuel_cost_per_km
    st.text_input(
        "Chi phí rỗng tránh được (VNĐ):",
        value=f"{saved_cost:,.0f} đ",
        disabled=True,
        help=f"Điểm hòa vốn = {avg_empty_km:.1f} km × {fuel_cost_per_km:,.0f} đ/km. Đây là ngân sách tối đa cho phép để đi vòng."
    )
    
    # 3. Tỷ lệ an toàn lợi nhuận (Người dùng nhập)
    safety_margin = st.slider(
        "Ngưỡng cho phép đi vòng (%):",
        min_value=50, max_value=100, value=80, step=5,
        help="Để có lợi nhuận, khoảng cách đi vòng phải thấp hơn điểm hòa vốn (Khuyên dùng 70-80%)."
    )
    
# --- TÍNH TOÁN KẾT QUẢ ĐẦU RA ---
# 1. Tính khoảng cách kết nối tối đa (Từ điểm Delivery cuối sang điểm Pickup đầu)
max_del_to_pic_km = avg_empty_km * (safety_margin / 100.0)

# 2. Tổng giới hạn quãng đường (Chạy ngầm để truyền vào Google OR-Tools Solver)
base_round_trip = avg_empty_km * 2
max_distance_km = int(base_round_trip + max_del_to_pic_km)

# Hiển thị trực quan trên giao diện
st.sidebar.markdown(f"**Khoảng cách TỐI ĐA từ điểm Giao $\\rightarrow$ Lấy:** `{max_del_to_pic_km:.1f} km`")
st.sidebar.caption(
    f"*(Luật ghép chuyến: Xe chỉ chạy sang điểm Pickup nếu khoảng cách $\le$ {max_del_to_pic_km:.1f} km)*"
)
# --- PHẦN 1: QUẢN LÝ DỮ LIỆU ĐƠN HÀNG ---
st.subheader("1. Dữ liệu Đơn hàng & Tọa độ")

if "orders_df" not in st.session_state:
    st.session_state.orders_df = pd.DataFrame({
        "NodeID": [0, 1, 2, 3, 4, 5, 6, 7],
        "Name": ["Kho Trung Tam Dong A", "KCN Tan Binh", "KCN Vinh Loc", "KCN Le Minh Xuan", "KCN Tan Tao", "KCN Hiep Phuoc", "KCN Cat Lai", "KCN Song Than"],
        "Type": ["Depot", "Delivery", "Delivery", "Delivery", "Delivery", "Pickup", "Pickup", "Pickup"],
        "Demand": [0, 15, 20, 15, 25, 20, 25, 15],
        "Lat": [10.8231, 10.8122, 10.8354, 10.7412, 10.7485, 10.6452, 10.7681, 10.9015],
        "Lon": [106.6297, 106.6201, 106.5752, 106.5284, 106.5821, 106.7451, 106.7865, 106.7482]
    })

edited_df = st.data_editor(
    st.session_state.orders_df, num_rows="dynamic", use_container_width=True,
    column_config={
        "Type": st.column_config.SelectboxColumn("Loại điểm", options=["Depot", "Delivery", "Pickup"], required=True),
        "Demand": st.column_config.NumberColumn("Demand (Tấn)"),
        "Lat": st.column_config.NumberColumn("Vĩ độ", format="%.6f"),
        "Lon": st.column_config.NumberColumn("Kinh độ", format="%.6f"),
    }
)
st.session_state.orders_df = edited_df
df = edited_df.dropna(subset=['Lat', 'Lon', 'Type']).reset_index(drop=True)

# --- DỰ TOÁN CHI PHÍ TRƯỚC TỐI ƯU ---
st.subheader("2. Phân tích & Tối ưu hóa")

if len(df) >= 2:
    depot_row = df[df['Type'] == 'Depot'].iloc[0]
    depot_lat, depot_lon = depot_row['Lat'], depot_row['Lon']
    
    manual_distance = 0
    manual_vehicles = 0
    
    for i, row in df.iterrows():
        if row['Type'] != 'Depot':
            dist = haversine_distance(depot_lat, depot_lon, row['Lat'], row['Lon'])
            manual_distance += dist * 2
            manual_vehicles += 1
            
    manual_cost = (manual_vehicles * fixed_vehicle_cost) + (manual_distance * fuel_cost_per_km)

    st.info(f"📊 **DỰ TOÁN GỐC (Vận hành thủ công 1 xe/1 đơn):** Cần điều động **{manual_vehicles} xe** | Tổng quãng đường: **{manual_distance:.1f} km** | Chi phí ước tính: **{manual_cost:,.0f} VNĐ**")

if st.button("🚀 Chạy Tối Ưu Hóa (AI Solver)"):
    if len(df) < 2:
        st.warning("Cần ít nhất 2 điểm để chạy.")
    else:
        with st.spinner("AI đang so sánh chi phí giữa các tổ hợp ghép xe và điều xe mới..."):
            distance_matrix = create_distance_matrix(df)
            
            deliveries = [row['Demand'] if row['Type'] == 'Delivery' else 0 for _, row in df.iterrows()]
            pickups = [abs(row['Demand']) if row['Type'] == 'Pickup' else 0 for _, row in df.iterrows()]
            
            manager = pywrapcp.RoutingIndexManager(len(distance_matrix), num_vehicles, 0)
            routing = pywrapcp.RoutingModel(manager)

            # 1. RÀNG BUỘC KHOẢNG CÁCH (Tạo giới hạn Km)
            def distance_callback(from_index, to_index):
                return distance_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
            
            dist_callback_index = routing.RegisterTransitCallback(distance_callback)
            routing.AddDimension(
                dist_callback_index,
                0,  # Không cho phép slack (thời gian trễ)
                int(max_distance_km * 1000),  # Giới hạn km quy ra mét
                True, 
                'Distance'
            )

            # 2. RÀNG BUỘC TÀI CHÍNH & LOGIC NGHIỆP VỤ (AI đếm bằng tiền VNĐ)
            def cost_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)
                
                # Cấm đi từ Pickup sang Delivery (Phạt 999 triệu VNĐ để AI né đường này)
                if df.iloc[from_node]['Type'] == 'Pickup' and df.iloc[to_node]['Type'] == 'Delivery':
                    return 999999999
                
                # Tính chi phí đoạn đường bằng VNĐ
                dist_m = distance_matrix[from_node][to_node]
                cost_vnd = int((dist_m / 1000.0) * fuel_cost_per_km)
                return cost_vnd

            cost_callback_index = routing.RegisterTransitCallback(cost_callback)
            # Ép AI tối ưu tìm tổng tiền VNĐ nhỏ nhất
            routing.SetArcCostEvaluatorOfAllVehicles(cost_callback_index)
            # Gắn phí xuất xe (Định phí) bằng VNĐ
            routing.SetFixedCostOfAllVehicles(int(fixed_vehicle_cost))

            # 3. RÀNG BUỘC TẢI TRỌNG (Giao đi và Lấy về)
            def delivery_callback(from_index):
                return deliveries[manager.IndexToNode(from_index)]
            delivery_callback_index = routing.RegisterUnaryTransitCallback(delivery_callback)
            routing.AddDimensionWithVehicleCapacity(delivery_callback_index, 0, vehicle_capacities, True, 'Delivery_Capacity')

            def pickup_callback(from_index):
                return pickups[manager.IndexToNode(from_index)]
            pickup_callback_index = routing.RegisterUnaryTransitCallback(pickup_callback)
            routing.AddDimensionWithVehicleCapacity(pickup_callback_index, 0, vehicle_capacities, True, 'Pickup_Capacity')

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            search_parameters.time_limit.seconds = 5 

            solution = routing.SolveWithParameters(search_parameters)

            if solution:
                total_distance = 0
                routes = []
                colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2']

                m = folium.Map(location=[depot_lat, depot_lon], zoom_start=11)

                for i, row in df.iterrows():
                    color = "black" if row['Type'] == 'Depot' else ("red" if row['Type'] == 'Delivery' else "green")
                    icon_type = "home" if row['Type'] == 'Depot' else ("arrow-up" if row['Type'] == 'Delivery' else "arrow-down")
                    folium.Marker(
                        [row['Lat'], row['Lon']],
                        popup=f"{row['Name']} ({row['Type']}) - Tải: {row['Demand']}T",
                        tooltip=row['Name'],
                        icon=folium.Icon(color=color, icon=icon_type, prefix='fa')
                    ).add_to(m)

                for vehicle_id in range(num_vehicles):
                    index = routing.Start(vehicle_id)
                    route_coords = []
                    route_nodes = []
                    route_distance = 0
                    route_del_load = 0
                    route_pic_load = 0
                    
                    while not routing.IsEnd(index):
                        node_index = manager.IndexToNode(index)
                        route_nodes.append(str(df.iloc[node_index]['Name']))
                        route_coords.append([df.iloc[node_index]['Lat'], df.iloc[node_index]['Lon']])
                        
                        route_del_load += deliveries[node_index]
                        route_pic_load += pickups[node_index]
                        
                        previous_index = index
                        index = solution.Value(routing.NextVar(index))
                        
                        # Tính khoảng cách thực tế từ ma trận km
                        dist_step = distance_matrix[manager.IndexToNode(previous_index)][manager.IndexToNode(index)]
                        route_distance += dist_step

                    node_index = manager.IndexToNode(index)
                    route_nodes.append(str(df.iloc[node_index]['Name']))
                    route_coords.append([df.iloc[node_index]['Lat'], df.iloc[node_index]['Lon']])
                    
                    actual_distance = route_distance / 1000.0

                    if len(route_nodes) > 2:
                        total_distance += actual_distance
                        folium.PolyLine(
                            route_coords, color=colors[vehicle_id % len(colors)], weight=5, opacity=0.8,
                            tooltip=f"Lộ trình {vehicle_names[vehicle_id]}"
                        ).add_to(m)
                        
                        routes.append({
                            "Biển số": vehicle_names[vehicle_id],
                            "Tải Max": f"{vehicle_capacities[vehicle_id]} T",
                            "Giao đi": f"{route_del_load} T",
                            "Lấy về": f"{route_pic_load} T",
                            "Quãng đường": f"{round(actual_distance, 2)} km",
                            "Lộ trình": " ➔ ".join(route_nodes)
                        })

                # --- TÍNH TOÁN TÀI CHÍNH SAU TỐI ƯU ---
                vehicles_used = len(routes)
                optimized_cost = (vehicles_used * fixed_vehicle_cost) + (total_distance * fuel_cost_per_km)
                savings = manual_cost - optimized_cost
                
                if optimized_cost <= max_acceptable_cost:
                    st.success(f"✅ **ĐẠT CHỈ TIÊU:** Hệ thống ghép điểm thành công dưới mức ngân sách tối đa.")
                else:
                    st.error(f"⚠️ **CẢNH BÁO:** Chi phí tối ưu ({optimized_cost:,.0f} VNĐ) VƯỢT ngân sách cho phép.")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Tổng chi phí Tối ưu", f"{optimized_cost:,.0f} đ", f"-{savings:,.0f} đ", delta_color="inverse")
                col2.metric("Số xe thực tế sử dụng", f"{vehicles_used} / {num_vehicles} xe", f"-{manual_vehicles - vehicles_used} chuyến")
                col3.metric("Tổng quãng đường", f"{round(total_distance, 2)} km", f"-{round(manual_distance - total_distance, 1)} km")
                col4.metric("Đơn lấy hàng (Backhaul)", f"{len(df[df['Type'] == 'Pickup'])} đơn ghép")

                st.subheader("Bản đồ điều phối trực quan")
                st_folium(m, width=1000, height=520, returned_objects=[])

                st.subheader("Chi tiết Lộ trình & Chỉ số tuân thủ")
                st.table(pd.DataFrame(routes))
            else:
                st.error("❌ Hệ thống AI không tìm được phương án ghép xe thỏa mãn điều kiện!")
                st.warning("""
                **Cách khắc phục:**
                1. **Quá xa:** Có điểm nằm vượt quá 'Giới hạn km mỗi xe' ➔ Hãy tăng giới hạn km lên.
                2. **Hết xe:** Số điểm bốc hàng xa quá nhiều nhưng số lượng xe không đủ để chạy thẳng từ kho ➔ Hãy tăng 'Số lượng xe điều phối'.
                3. **Quá tải:** Tải trọng của 1 đơn lớn hơn sức chở của 1 chiếc xe ➔ Kiểm tra lại Tải trọng xe.
                """)
