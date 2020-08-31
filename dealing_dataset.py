import sqlite3

conn = sqlite3.connect(r"nlpdata.db")\


def create_dataset_ep(table):
    cursor = conn.cursor()
    sql = "select * from " + table + " LIMIT 20"
    cursor.execute(sql)
    conn.commit()

    dataset = []

    for row in cursor:
        eid = row[0]
        tag = row[1]
        content = row[2]
        if tag == "5" or tag == "4":
            dataset.append([eid, 2, content])
            print(eid, 2, content)
        elif tag == "1" or tag == "2":
            dataset.append([eid, 0, content])
            print(eid, 0, content)
        else:
            dataset.append([eid, 1, content])
            print(eid, 1, content)
    return dataset


def create_dataset_pdt():
    conn_pdt = sqlite3.connect(r".\bptdata.db")
    cursor = conn_pdt.cursor()
    sql = "select * from " + "predict_data"
    cursor.execute(sql)
    conn_pdt.commit()

    dataset = []

    for row in cursor:
        stnid = row[0]
        text = row[1]
        dataset.append([stnid, 0, text])
        print(stnid, 0, text)

    return dataset


if __name__ == '__main__':
    print(create_dataset_ep("amki_test"))