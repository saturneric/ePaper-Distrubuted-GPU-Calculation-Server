import os
import shutil

import requests
import datetime
import time
import hashlib
import sqlite3
import pandas
import threading
import logging as log

server_url = "http://39.100.94.111:8083"
openid = "gpu-server-test1"
password = "1e327b070ab43fd071768a4d474f016adbbf3ea475577fe66a505d9e33b24f2f"
token = None
# 客户端代码
client_code = "dc9fbb4f4f0b84fa903058991af60e73556494af8a02ef69fb6a93217729f04b"
# 护照认证码
idcode = None
# 时间戳
timestamp = ""
# 单次最大处理句数
max_stn_num = 20000
# 当前处理的bpt的序号
bpt_id = 0
# STNS
stn_list = []
# 输入数据存储表
predict_table = "predict_data"
# 模型处理结果输出文件夹
result_out_dir = "./tmp/eppredict"
# 初始化标志位
base_init = False

log.basicConfig(filename=None, format="%(asctime)s %(levelname)s [%(funcName)s] : %(message)s", level=log.INFO)


def get_timestamp():
    return str(int(time.mktime(datetime.datetime.now().timetuple())) * 1000)


base_headers = {"timestamp": get_timestamp(), "X-Requested-With": ""}
token_headers = {"timestamp": get_timestamp(), "X-Requested-With": "", "signed": "", "openid": openid}


# url对象
def url_parser(url):
    return server_url + "/" + url


# 计算随机特征值
def calculate_random_code():
    return hashlib.sha1("RandomCode [{0}][{1}][{2}]".format(openid, get_timestamp(), client_code).encode("utf-8")) \
        .hexdigest()


# 计算客户端签名
def calculate_signed():
    return hashlib.sha1("SIGN [{0}][{1}][{2}]".format(openid, calculate_random_code(), token).encode("utf-8")) \
        .hexdigest()


# 检查用户是否存在
def user_checker():
    log.info("Check User Existence: openid" + str(openid))
    checker_param = {"openid": openid}
    base_headers["timestamp"] = get_timestamp()
    res = requests.get(url=url_parser("user"), headers=base_headers, params=checker_param)
    if res.status_code == 404:
        log.warning("User Not Exist: openid" + str(openid))
        return False
    else:
        log.info("User Exist: openid " + str(openid))
        return True


# 注册用户
def user_register():
    if not user_checker():
        log.info("Try Creating New User: openid " + str(openid))
        register_json = {"openid": openid, "password": password}
        register_param = {"clientCode": client_code}
        base_headers["timestamp"] = get_timestamp()
        res = requests.post(url=url_parser("user/cs"), headers=base_headers, json=register_json, params=register_param)
        respond_json = res.json()
        if res.status_code == 201 and respond_json["openid"] == openid:
            log.info("User Creation Success: openid " + str(openid))
            return False
        else:
            log.error("User Creation Failed: openid " + str(openid))
            return True


# 获得token
def get_token():
    if user_checker():
        log.info("Try Getting New Token")
        login_json = {"openid": openid, "password": password, "clientCode": client_code}
        res = requests.post(url=url_parser("user/login"), headers=base_headers, json=login_json)
        respond_json = res.json()
        if res.status_code == 200 and respond_json["info"] == "Authentication Success":
            global token
            token = respond_json["data"]["token"]
            log.info("Succeed In Getting New Token" + str(token))
        else:
            if base_init is True:
                user_register()
            log.error("Fail To Get New Token")


# 获得子服务器护照
def get_csp():
    global idcode
    if token is not None:
        log.info("Try Getting New CSP")
        # 计算客户端签名
        token_headers["signed"] = calculate_signed()
        token_headers["timestamp"] = get_timestamp()
        res = requests.post(url=url_parser("cs"), headers=token_headers)
        respond_json = res.json()
        log.debug(respond_json)
        # 正常返回
        if res.status_code == 200:
            # 无权限检查
            try:
                idcode = respond_json["identityCode"]
                log.info("Succeed In Getting CSP: idcode " + str(idcode))
            except KeyError:
                if respond_json["status"] == 401:
                    log.warning("Token OUT OF DATE: token " + str(token))
                    get_token()
                    return

        # 无权限返回
        elif res.status_code == 401:
            # 重新获取token
            log.warning("Token Maybe OUT OF DATE: token " + str(token))
            log.info("Try to Get New Token")
            get_token()
        else:
            log.error("Failed to get New CSP")
    else:
        get_token()


# 更新签证
def update_csp():
    if idcode is not None:
        token_headers["signed"] = calculate_signed()
        token_headers["timestamp"] = get_timestamp()
        res = requests.put(url=url_parser("cs"), headers=token_headers, params={"idcode": idcode})
        respond_json = res.json()
        log.debug(respond_json)
        # 成功返回
        if res.status_code == 200 and respond_json["expired"] is False:
            log.info("Succeed IN Updating CSP: idcode " + str(idcode))
            log.info("CSP Last Update Time: " + str(respond_json["lastUpdateTime"]))
        elif res.status_code == 401:
            # 尝试获得新的token
            log.warning("Unauthorized Status Code: Try to Get New Token")
            get_token()
        else:
            # 重新获得护照
            log.warning("CSP Maybe OUT OF DATE: idcode " + str(idcode))
            get_csp()


# 放弃批处理任务
def giving_up_bpt():
    global bpt_id
    global stn_list
    try_count = 3
    while try_count < 3:
        try_count += 1
        # 标记任务执行失败
        res = requests.put(url=url_parser("cs/bpt"),
                           headers=token_headers,
                           params={"idcode": idcode, "bptId": bpt_id, "status": False},
                           json=[])

        if res.status_code == 201:
            log.info("Marking Task Failed Successful: bertId ", bpt_id)
            return True
        elif res.status_code == 401:
            # 尝试获得新的token
            log.warning("Unauthorized Status Code: Try to Get New Token")
            get_token()
        else:
            if try_count >= 3:
                log.error("Marking Task Failed Eventually Failed: bertId ", bpt_id)
                log.warning("Connection Maybe Unstable")
                return False
        log.warning("Failed and Try: count " + str(try_count))

        # 清空计算数据
        bpt_id = None
        stn_list = []


# 从主服务器获得批处理任务
def get_bpt_from_server():
    global max_stn_num
    global idcode
    if idcode is not None:
        log.info("Try Getting BPT From Server...")
        token_headers["signed"] = calculate_signed()
        token_headers["timestamp"] = get_timestamp()
        res = requests.get(url=url_parser("cs/bpt"),
                           headers=token_headers,
                           params={"idcode": idcode, "maxStnNum": int(max_stn_num)})
        respond_json = res.json()
        print(res.json())
        if res.status_code == 200:
            global bpt_id
            try:
                bpt_id = respond_json["id"]
            except KeyError:
                if respond_json["status"] == 401:
                    get_token()
                    return

            # 如果没有批处理任务
            if bpt_id is None:
                log.info("No BPT Task For Now")
                return

            stns = respond_json["stns"]
            if len(stns) == 0:

                log.info("STNS IS EMPTY, Giving UP")
                giving_up_bpt()
                return

            log.info("Get BPT Task: bptId " + str(bpt_id))
            global stn_list
            stn_list = stns
            conn = sqlite3.connect(r".\bptdata.db")
            # 处理数据
            cursor = conn.cursor()
            cursor.execute("DELETE FROM {0}".format(predict_table))

            log.info("Processing Bert Predict Data...")
            for stn in stns:
                sql = "INSERT INTO {0} (id, text) values (?, ?)".format(predict_table)
                cursor.execute(sql, [stn["stnId"], stn["text"]])
            conn.commit()
            conn.close()
            log.info("Finished in Processing Bert Predict Data")

            result = execute_bert_predict()

            if result is True:
                if processing_bert_result() is True:
                    log.info("BPT Execution Success: bptId " + str(bpt_id))
                else:
                    log.info("BPT Execution Eventually Failed: bptId " + str(bpt_id))
            else:
                log.error("Bert Model Execution Failed")

                log.info("Try Giving Up BPT Task: bptId " + str(bpt_id))
                giving_up_bpt()

                log.info("Get Status Code: " + str(res.status_code))

            # 清空计算数据
            bpt_id = None
            stn_list = []

        elif res.status_code == 400:
            if respond_json["data"]["exception"] == "org.codedream.epaper.exception.badrequest.AuthExpiredException":
                print("Auth Expired Exception: Try to Get New CSP")
                get_csp()
                return
            else:
                print("Unknown Exception")

        elif res.status_code == 401:
            # 尝试获得新的token
            log.warning("Unauthorized Status Code: Try to Get New Token")
            get_token()
        elif res.status_code == 500:
            log.warning("Remote Server Error: Inner Server Error")
            print(res.json())
    else:
        # 尝试获得护照
        get_csp()


#  初始化数据库环境
def sqlite_create_table():
    conn = sqlite3.connect(r".\bptdata.db")
    cursor = conn.cursor()
    create_tb_cmd = "CREATE TABLE IF NOT EXISTS {0}" \
                    "(id INT PRIMARY KEY," \
                    "text INT)".format(predict_table)
    cursor.execute(create_tb_cmd)
    cursor.execute("DELETE FROM {0}".format(predict_table))
    conn.commit()
    conn.close()


# 启动BERT神经网络模型
def execute_bert_predict():
    if os.path.exists(result_out_dir):
        shutil.rmtree(result_out_dir)
    log.info("BERT Model Executing...")
    os.system("python run_classifier.py "
              "--task_name=eppdt "
              "--do_predict=true "
              "--data_dir=./tmp "
              "--vocab_file=./chinese_wwm_ext_L-12_H-768_A-12/vocab.txt "
              "--bert_config_file=./chinese_wwm_ext_L-12_H-768_A-12/bert_config.json "
              "--init_checkpoint=./tmp/epout/model.ckpt-14062 "
              "--max_seq_length=64 "
              "--output_dir=./tmp/eppredict/ > bert_out.log 2>&1")
    result_list = os.listdir(result_out_dir)
    log.info("BERT Model Execution Finished.")
    if "test_results.tsv" not in result_list:
        return False
    else:
        return True


# 处理模型计算结果
def processing_bert_result():
    result = pandas.read_csv(result_out_dir + '/test_results.tsv', sep='\t', header=None)
    token_headers["timestamp"] = get_timestamp()
    token_headers["signed"] = calculate_signed()
    bpt_result_json = []
    idx = 0

    for i, row in result.iterrows():
        bpt_result_json.append({"stnid": stn_list[idx]["stnId"], "tagPossible": [row[0], row[1], row[2]]})
        idx += 1

    log.debug("Bert Result Json")
    log.debug(bpt_result_json)
    log.info("Processing BERT Model Result Successful")

    # 尝试3次
    try_count = 0
    while try_count < 3:
        try_count += 1
        log.info("Uploading BERT Model Result...")
        res = requests.put(url=url_parser("cs/bpt"),
                           headers=token_headers,
                           params={"idcode": idcode, "bptId": bpt_id, "status": True},
                           json=bpt_result_json)
        if res.status_code == 201:
            log.info("Uploading Successful: bertId " + str(bpt_id))
            return True
        elif res.status_code == 401:
            # 尝试获得新的token
            log.warning("Unauthorized Status Code: Try to Get New Token")
            get_token()
        else:
            if try_count >= 3:
                log.error("Uploading Eventually Failed: bertId " + str(bpt_id))
                log.warning("Connection Maybe Unstable")
                return False
        log.warning("Failed and Try: count " + str(try_count))


# 签证更新多线程定时器
def update_csp_timer():
    log.info("UPDATE CSP TIMER STARTED")
    try:
        update_csp()
    except:
        log.error("Exception Thrown, Restarting Timer...")
    finally:
        t = threading.Timer(60, update_csp_timer)
        t.start()


# 批处理任务多线程定时器
def get_bpt_timer():
    log.info("GET BPT TIMER STARTED")
    try:
        get_bpt_from_server()
    except:
        log.error("Exception Thrown, Restarting Timer...")
    finally:
        t = threading.Timer(15, get_bpt_timer)
        t.start()


# 初始化工作
def init():
    global base_init
    sqlite_create_table()
    user_register()
    get_token()
    get_csp()
    base_init = True


# 初始化定时器
def init_timer():
    update_csp_timer()
    get_bpt_timer()


if __name__ == "__main__":
    try_time = 0
    while try_time < 3:
        try:
            init()
            try_time = 3
        except:
            try_time += 1
            time.sleep(5)

    init_timer()
    while True:
        time.sleep(5)
