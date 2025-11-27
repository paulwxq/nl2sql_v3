## 项目背景
当前模块的主要执行步骤，Step 1-> Step2 ->Step3->step4->step5, 以及 Step 1-> Step 6.
Step 1.生成 ddl，连接到数据库，获取表结构，生成ddl，包括注释。 文件类型为 *.sql，路径为：\output\metaweave\metadata\ddl，在当前的基础上添加3条记录，需要设计一个格式，保存3条记录。
Step 2.生成 json(表和字段的数据画像)，基于step 1生成的ddl语句，为字段和表生成画像，写入到json中, 路径为：\output\metaweave\metadata\json。关于表结构，要从前面的ddl获取，包括里面的主外键和唯一约束等信息，不要从表中获取。
step 3.生成 json(表之间的关联关系)，基于step2生成数据画像的json文件，按照预订的算法，找出来表之间的关联关系，并写入到Json文件中，路径为：\output\metaweave\metadata\rel 
Step 4.生成 neo4j cql，基于step 2生成的数据画像json和step 3生成的关联关系，以及从数据库中获取的数据和统计指标，生成neo4j的cql，它的路径为：\output\metaweave\metadata\cql . 这里的neo4j的cql，可以直接执行，写入到neo4j中。 
Step 5.数据加载：
  - cql : 根据 step 3 和 step 4 生成的结果，把step 4生产的neo4j cql，写入到neo4j中。

## 模块需求
现在我们已经完成了 Step 1-> Step2 ->Step3, 接下来我们要完成 Step 4.
接下来，我们要写一篇step4的设计文档，step4主要是根据step3的生成物，生成neo4j中创建节点和边的cql.
需要创建两种类型的节点，Table 和 Column，Table 和 Column 之间是 HAS_COLUMN的关系。
也就是说，node的标签有两种：Table、Column，边的标签有两种：HAS_COLUMN，JOIN_ON，注意它们的大小写，我们要严格区分。

#### Table的属性如下：
- <id>，系统自动生成的内部id
- full_name，或者改为 id: "id: public.dim_region"
- schema
- name
- comment
- pk
- uk
- fk
- logic_pk
- logic_fk
- logic_uk
- indexes

#### Column的属性：
- <id>，系统自动生成的内部id
- full_name，或者叫 id: "id: public.dim_store.store_id"
- comment: 店铺ID（主键）
- is_fk: false
- is_measure: false
- is_pk: true
- is_time: false
- is_uk: false
- name: store_id
- pk_position: 0
- schema: public
- table: dim_store

#### Table与Column 直接的关系：
HAS_COLUMN的属性如下：
- <id>, 系统自动生成的内部id


#### 有关联的表之间是 JOIN_ON 的关系：
JOIN_ON 边的属性：
- <id>，系统自动生成的内部id
- cardinality	N:1
- constraint_name: fk_store_company
- join_type: INNER JOIN
- on: SRC.company_id = DST.company_id

现在请你写一篇文档，来做这个设计，如何根据 step 3+step 4的输出物，生产 cql 语句。
生成的cql语句最终会被写入到neo4j数据库，而写入neo4j的数据将被后面的生成SQL的模块所使用，你可以搜索下面模块代码，了解生成SQL子图模块是如何访问Neo4j的，了解这些内容对你设计Step4的文档会非常有帮助。分析SQL子图模块代码后，顺便告诉我它是否使用apoc的模块。

## 设计要求
在你设计的时候，要注意以下事项：
1.对于"SQL生成子图"模块在进行表之间关联查询的时候,对于使用不到的节点的属性，你可以根据自己的经验来进行设计，对于"SQL生成子图"模块已经在使用的属性或者关键字，如果需要修改，请你注明，以便当前模块完成开发后，在修改"SQL生成子图"模块.
2.生成cql的原料来自于step3 和 step2 生成的文件：
step2: ./output/metaweave/metadata/json/*.json , 这个目录下的*.json是所有表和字段的数据画像。
step3: ./output/metaweave/metadata/rel/*.json 和 *.md ， *.json 文件是关联关系，*.md 文件是总结。
理论上只需要访问上述两个目录的文件即可完成cql 语句的生成。
3.生成的cql文件，放在这个目录下：./output/metaweave/metadata/cql/，在后续的step5中，能够连接到neo4j，把cql/目录下的文件写入到neo4j中，创建节点和表。
4.step4 使用的配置文件在 ./configs/metaweave/metadata_config.yaml
5.项目使用的neo4j的版本是 >= v5.7.x，neo4j的配置在项目根目录下的 .env 文件中，但我认为当前step4 用不到neo4j的连接，step4 只是生成cql文件。
# ⚠️ 需要填写：Neo4j 连接信息
NEO4J_URI=bolt://localhost:7687   # Neo4j 连接URI
NEO4J_USER=neo4j                   # Neo4j 用户名
NEO4J_PASSWORD=wxq79101            # ⚠️ 必填：Neo4j 密码
NEO4J_DATABASE=neo4j               # Neo4j 数据库名
6.使用下面的命令，即可执行step4,在./output/metaweave/metadata/cql/生成 *.cypher 文件
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql
